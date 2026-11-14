"""Pytest fixtures."""

from __future__ import annotations

from datetime import date

import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import DailyObservation
from tests.data_fixtures import generate_test_rainfall


@pytest.fixture()
def app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + (tmp_path / "test.db").as_posix()
        AUTO_TRAIN_MODEL = False
        FORECAST_ENABLED = False
        INGEST_DIR = tmp_path
        IMERG_PATTERN = "*.nc4"
        MODELS_DIR = tmp_path / "models"

    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        frame = generate_test_rainfall(date(2015, 1, 1), date(2024, 12, 31), seed=7)
        db.session.bulk_save_objects(
            [
                DailyObservation(
                    day=row.day,
                    precip_mm=float(row.precip_mm),
                    coverage_pct=100.0,
                    source="imerg_final_daily",
                    qc_flag="test",
                )
                for row in frame.itertuples(index=False)
            ]
        )
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
