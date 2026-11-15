from __future__ import annotations

from datetime import date

import pandas as pd

from app.extensions import db
from app.models import DailyObservation
from app.services.series_service import calendar_series, daily_series


def _seed(app, days):
    with app.app_context():
        db.session.query(DailyObservation).delete()
        for day, mm in days:
            db.session.add(
                DailyObservation(
                    day=day,
                    precip_mm=mm,
                    coverage_pct=100.0,
                    source="imerg_final_daily",
                    qc_flag="test",
                )
            )
        db.session.commit()


def test_calendar_series_fills_gaps_with_nan(app):
    _seed(app, [(date(2024, 1, 1), 5.0), (date(2024, 1, 4), 2.0)])

    with app.app_context():
        series = calendar_series()

    assert len(series) == 4
    assert series.index[0] == pd.Timestamp("2024-01-01")
    assert series.index[-1] == pd.Timestamp("2024-01-04")
    assert series.iloc[0] == 5.0
    assert pd.isna(series.iloc[1])
    assert pd.isna(series.iloc[2])
    assert series.iloc[3] == 2.0


def test_daily_series_keeps_only_observed_days(app):
    _seed(app, [(date(2024, 1, 1), 5.0), (date(2024, 1, 4), 2.0)])

    with app.app_context():
        series = daily_series()

    assert len(series) == 2


def test_calendar_series_is_empty_without_observations(app):
    with app.app_context():
        db.session.query(DailyObservation).delete()
        db.session.commit()
        series = calendar_series()

    assert series.empty
