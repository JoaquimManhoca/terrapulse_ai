"""Tests for the /api/climate/trends endpoint."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import DailyObservation


@pytest.fixture()
def seeded_seasons(app):
    """12 seasons with a clear decreasing trend: 800 - 30 * (season-2000) mm."""
    with app.app_context():
        DailyObservation.query.delete()
        for season in range(2000, 2012):
            total_target = max(200.0, 800.0 - 30.0 * (season - 2000))
            day = date(season, 10, 1)
            while day <= date(season + 1, 3, 31):
                db.session.add(
                    DailyObservation(
                        day=day, precip_mm=total_target / 183.0, source="imerg_final_daily"
                    )
                )
                day += timedelta(days=1)
        db.session.commit()


def test_climate_trends_endpoint(client, seeded_seasons):
    response = client.get("/api/climate/trends")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["n_seasons"] == 12
    assert payload["data_status"] == "real"
    assert payload["confidence_level"] == 0.95

    seasons = payload["seasons"]
    assert [s["season"] for s in seasons] == list(range(2000, 2012))
    assert seasons[0]["total_mm"] > seasons[-1]["total_mm"]
    assert all(s["real_pct"] == 100.0 for s in seasons)

    trend = payload["trend_seasonal"]
    assert trend["trend"] == "decreasing"
    assert trend["p_value"] < 0.05

    slope = payload["slope_seasonal"]
    assert slope["slope"] < 0
    assert slope["ci_low"] <= slope["slope"] <= slope["ci_high"]

    comparison = payload["period_comparison"]
    assert comparison["significant"] is True
    assert comparison["difference"] < 0

    assert payload["recent_mean"]["ci_low"] < payload["recent_mean"]["ci_high"]
    assert payload["baseline_mean"]["mean"] > payload["recent_mean"]["mean"]


def test_climate_trends_november_series(client, seeded_seasons):
    payload = client.get("/api/climate/trends").get_json()
    assert payload["trend_november"]["n"] == 12
    assert payload["trend_november"]["trend"] == "decreasing"


def test_climate_trends_excludes_synthetic_seasons(client, seeded_seasons):
    """Seasons below the real-data threshold are excluded from statistics."""
    with client.application.app_context():
        db.session.add_all(
            [
                DailyObservation(
                    day=date(2025, 11, 5), precip_mm=5.0, source="synthetic"
                ),
                DailyObservation(
                    day=date(2026, 1, 5), precip_mm=5.0, source="synthetic"
                ),
            ]
        )
        db.session.commit()

    payload = client.get("/api/climate/trends").get_json()
    assert payload["n_seasons"] == 13  # 12 real + 1 synthetic season 2025
    assert payload["seasons_used"] == 12
    assert payload["seasons_excluded"] == 1
    assert payload["trend_seasonal"]["n"] == 12


def test_climate_trends_insufficient_data(app):
    with app.app_context():
        DailyObservation.query.delete()
        db.session.commit()
    response = app.test_client().get("/api/climate/trends")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "insufficient_data"
