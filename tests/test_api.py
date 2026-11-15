from __future__ import annotations

import csv
from datetime import date
from uuid import uuid4


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["observations"] > 0
    assert payload["real_observations"] == payload["observations"]
    assert payload["synthetic_observations"] == 0
    assert payload["data_status"] == "real"


def test_feedback_records_one_tap_choice(client, app):
    from app.models import DecisionFeedback

    submission_id = str(uuid4())
    response = client.post(
        "/feedback",
        json={
            "submission_id": submission_id,
            "choice": "planted",
            "state": "PLANT_NOW",
            "confidence": 0.82,
            "model_version": "heuristic-v0",
            "last_day": "2025-01-05",
            "reference_date": "2025-01-05",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["feedback"]["choice"] == "planted"
    with app.app_context():
        record = DecisionFeedback.query.one()
        assert record.choice == "planted"
        assert record.state == "PLANT_NOW"
        assert record.confidence == 0.82
        assert record.region == "manica"
        assert record.crop == "milho"
        assert record.lang == "pt"
        assert record.last_observation == date(2025, 1, 5)


def test_feedback_submission_is_idempotent(client, app):
    from app.models import DecisionFeedback

    submission_id = str(uuid4())
    first = client.post(
        "/feedback",
        json={
            "submission_id": submission_id,
            "choice": "planted",
            "state": "PLANT_NOW",
        },
    )
    retry = client.post(
        "/feedback",
        json={
            "submission_id": submission_id,
            "choice": "waited",
            "state": "WAIT",
        },
    )

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.get_json()["feedback"]["choice"] == "planted"
    with app.app_context():
        assert DecisionFeedback.query.count() == 1


def test_feedback_rejects_invalid_choice(client, app):
    from app.models import DecisionFeedback

    response = client.post(
        "/feedback",
        json={
            "submission_id": str(uuid4()),
            "choice": "maybe",
            "state": "WAIT",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_feedback"
    with app.app_context():
        assert DecisionFeedback.query.count() == 0


def test_feedback_rejects_missing_submission_id(client):
    response = client.post(
        "/feedback",
        json={"choice": "waited", "state": "WAIT"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_feedback"


def test_feedback_form_fallback_redirects(client):
    response = client.post(
        "/feedback",
        data={
            "submission_id": str(uuid4()),
            "choice": "waited",
            "state": "WAIT",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/?feedback=1")


def test_feedback_cli_summary_and_csv_export(app, tmp_path):
    from app.extensions import db
    from app.models import DecisionFeedback

    with app.app_context():
        db.session.add(
            DecisionFeedback(
                submission_id=str(uuid4()),
                decision_date=date(2025, 1, 5),
                choice="planted",
                state="PLANT_NOW",
                confidence=0.82,
                model_version="=1+1",
                region="manica",
                crop="milho",
                lang="pt",
            )
        )
        db.session.commit()

    runner = app.test_cli_runner()
    summary = runner.invoke(args=["feedback-summary"])
    assert summary.exit_code == 0
    assert "Total responses: 1" in summary.output
    assert "planted: 1" in summary.output

    output = tmp_path / "feedback.csv"
    exported = runner.invoke(
        args=["feedback-export", "--output", str(output)]
    )
    assert exported.exit_code == 0
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["choice"] == "planted"
    assert rows[0]["model_version"] == "'=1+1"


def test_feedback_schema_upgrade_adds_missing_idempotency_column(app):
    from sqlalchemy import inspect

    from app.extensions import db

    with app.app_context():
        with db.engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP INDEX uq_decision_feedback_submission_id"
            )
            connection.exec_driver_sql(
                "ALTER TABLE decision_feedback DROP COLUMN submission_id"
            )

    result = app.test_cli_runner().invoke(
        args=["upgrade-feedback-schema"]
    )

    assert result.exit_code == 0, result.output
    assert "Feedback schema is ready." in result.output
    with app.app_context():
        inspector = inspect(db.engine)
        columns = {
            column["name"]
            for column in inspector.get_columns("decision_feedback")
        }
        indexes = {
            index["name"] for index in inspector.get_indexes("decision_feedback")
        }
    assert "submission_id" in columns
    assert "uq_decision_feedback_submission_id" in indexes


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
