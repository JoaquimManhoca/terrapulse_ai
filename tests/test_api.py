from __future__ import annotations

from datetime import date


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["observations"] > 0
    assert payload["real_observations"] == payload["observations"]
    assert payload["synthetic_observations"] == 0
    assert payload["data_status"] == "real"


def test_decision_contract(client):
    response = client.get("/api/decision")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["state"] in {"PLANT_NOW", "WAIT", "PLANT_IN_DAYS", "HIGH_RISK"}
    assert 0 <= payload["confidence"] <= 1
    assert payload["model_version"] == "heuristic-v0"
    assert isinstance(payload["reasons"], list) and payload["reasons"]
    assert payload["data_status"] == "real"
    assert "onset_21d" in payload["probabilities"]
    assert payload["probabilities"]["onset_21d"] is None


def test_decision_blocks_stale_data(client, app, monkeypatch):
    from app.services import decision as decision_service

    app.config["FORECAST_ENABLED"] = True
    monkeypatch.setattr(
        decision_service, "_local_today", lambda: date(2026, 11, 14)
    )

    def fail_forecast():
        raise AssertionError("stale data must not fetch a forecast")

    monkeypatch.setattr(decision_service, "fetch_open_meteo", fail_forecast)

    payload = client.get("/api/decision").get_json()

    assert payload["data_stale"] is True
    assert payload["data_age_days"] > 7
    assert payload["state"] == "WAIT"
    assert payload["days_to_plant"] is None
    assert payload["forecast"] is None
    assert "dados antigos" in payload["recommendation"]
    assert payload["reasons"][0]["code"] == "data_stale"
    assert all(reason["code"] != "forecast_rain" for reason in payload["reasons"])


def test_decision_accepts_fresh_data(client, monkeypatch):
    from app.services import decision as decision_service

    monkeypatch.setattr(
        decision_service, "_local_today", lambda: date(2025, 1, 5)
    )

    payload = client.get("/api/decision").get_json()

    assert payload["data_stale"] is False
    assert all(reason["code"] != "data_stale" for reason in payload["reasons"])


def test_forecast_summary_ignores_past_rows(monkeypatch):
    from app.services import decision as decision_service

    monkeypatch.setattr(
        decision_service, "_local_today", lambda: date(2026, 11, 14)
    )
    forecast = {
        "source": "test",
        "rows": [
            {"date": "2026-11-12", "weather_code": 61, "precip_mm": 30.0},
            {"date": "2026-11-14", "weather_code": 61, "precip_mm": 2.0},
            {"date": "2026-11-15", "weather_code": 61, "precip_mm": 1.0},
        ],
    }

    summary = decision_service._forecast_summary(
        forecast, date(2026, 11, 14), "pt"
    )

    assert summary["rain_7d"] == 3.0
    assert [row["date"] for row in summary["daily"]] == [
        "14/11",
        "15/11",
    ]


def test_decision_plan_has_forecast_and_climatology(client, app, monkeypatch):
    from datetime import date, timedelta

    from app.services import decision as decision_service

    app.config["FORECAST_ENABLED"] = True
    today = date(2025, 1, 5)
    monkeypatch.setattr(decision_service, "_local_today", lambda: today)
    monkeypatch.setattr(
        decision_service,
        "fetch_open_meteo",
        lambda: {
            "source": "open-meteo",
            "rows": [
                {
                    "date": (today + timedelta(days=offset)).isoformat(),
                    "weather_code": 0,
                    "precip_mm": 0.0,
                    "probability_pct": 10,
                }
                for offset in range(16)
            ],
        },
    )

    payload = client.get("/api/decision").get_json()
    plan = payload["plan"]

    assert len(plan["days"]) == 30
    assert plan["forecast_days"] == 16
    assert plan["climate_days"] == 14
    assert plan["days"][0]["phase"] == "forecast"
    assert plan["days"][15]["phase"] == "forecast"
    assert plan["days"][16]["phase"] == "climate"
    assert plan["days"][16]["probability_pct"] is not None
    assert plan["climate_years"] == 10


def test_decision_plan_falls_back_to_climatology(client, app, monkeypatch):
    from datetime import date

    from app.services import decision as decision_service

    app.config["FORECAST_ENABLED"] = False
    monkeypatch.setattr(
        decision_service, "_local_today", lambda: date(2025, 1, 5)
    )

    payload = client.get("/api/decision").get_json()
    plan = payload["plan"]

    assert plan["forecast_days"] == 0
    assert plan["climate_days"] == 30
    assert plan["has_forecast"] is False
    assert all(day["phase"] == "climate" for day in plan["days"])


def test_decision_trust_reports_sources_and_coverage(client, app, monkeypatch):
    from datetime import date

    from app.services import decision as decision_service

    app.config["FORECAST_ENABLED"] = False
    monkeypatch.setattr(
        decision_service, "_local_today", lambda: date(2025, 1, 5)
    )

    trust = client.get("/api/decision").get_json()["trust"]

    assert trust["sources_label"] == "IMERG Final"
    assert trust["coverage_pct"] == 100.0
    assert trust["observation_days"] > 0
    assert trust["history_years"] == 10
    assert trust["level"] in {"high", "medium", "low"}
    assert trust["change"]


def test_history_endpoint(client):
    response = client.get("/api/history?days=30")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["days"] <= 30
    assert isinstance(payload["series"], list)


def test_history_endpoint_rejects_non_integer_days(client):
    response = client.get("/api/history?days=abc")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_days"


def test_climatology_endpoint(client):
    response = client.get("/api/climatology")
    assert response.status_code == 200
    payload = response.get_json()
    assert "monthly" in payload and "yearly" in payload


def test_ingest_endpoint_on_empty_directory(client):
    response = client.post("/api/admin/ingest")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ingested"] == 0
    assert payload["updated"] == 0
    assert payload["days"] == 0
