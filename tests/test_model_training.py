"""Tests for model training, persistence and decision integration."""

from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.ml.classifier import train_onset_classifier
from app.ml.persistence import MODEL_VERSION, load_active_model, save_model
from app.ml.training_data import (
    FEATURE_COLUMNS,
    build_inference_frame,
    build_onset_dataset,
    split_by_season,
)
from app.models import DailyObservation
from app.services.decision import build_decision
from app.services.training import ensure_trained_model, train_and_persist
from tests.test_classifier import _complete_rainfall_seasons
from tests.data_fixtures import generate_test_rainfall


def test_train_and_persist_makes_model_active(app):
    with app.app_context():
        record = train_and_persist()

        assert record["version"] == MODEL_VERSION
        assert record["data_status"] == "real"
        assert record["metrics"]["test"]["rows"] > 0

        payload = build_decision()
        assert payload["model_version"] == MODEL_VERSION
        assert 0 <= payload["probabilities"]["onset_21d"] <= 1
        reason_codes = {reason["code"] for reason in payload["reasons"]}
        assert "ml_onset_prob" in reason_codes


def test_ensure_trained_model_does_not_retrain(app):
    with app.app_context():
        first = ensure_trained_model()
        assert first is not None
        second = ensure_trained_model()
        assert second["saved_at"] == first["saved_at"]


def test_ensure_trained_model_replaces_legacy_mixed_model(app):
    with app.app_context():
        train_and_persist()
        bundle = load_active_model(app.config["MODELS_DIR"])
        assert bundle is not None
        model, metadata = bundle
        metadata["data_status"] = "mixed"
        save_model(model, metadata, app.config["MODELS_DIR"])

        assert build_decision()["model_version"] == "heuristic-v0"
        refreshed = ensure_trained_model()

        assert refreshed is not None
        assert refreshed["data_status"] == "real"
        assert build_decision()["model_version"] == MODEL_VERSION


def test_model_round_trip_keeps_predictions(tmp_path):
    dataset = build_onset_dataset(_complete_rainfall_seasons())
    splits = split_by_season(dataset)
    model, _ = train_onset_classifier(splits)
    test_features = splits["test"].loc[:, list(FEATURE_COLUMNS)]
    before = model.predict_proba(test_features)

    save_model(model, {"metrics": {}, "splits": {}}, tmp_path / "models")
    loaded, stored = load_active_model(tmp_path / "models")
    assert stored["version"] == MODEL_VERSION
    after = loaded.predict_proba(test_features)
    assert (before == after).all()


def test_train_endpoint_returns_model_record(client, admin_headers):
    response = client.post("/api/admin/train", headers=admin_headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["version"] == MODEL_VERSION
    assert set(payload["metrics"]) == {"validation", "test"}

    decision = client.get("/api/decision").get_json()
    assert decision["model_version"] == MODEL_VERSION


def test_training_without_data_falls_back(app):
    with app.app_context():
        db.session.query(DailyObservation).delete()
        db.session.commit()
        with pytest.raises(ValueError):
            train_and_persist()
        payload = build_decision()
        assert payload["model_version"] == "heuristic-v0"


def test_training_rejects_synthetic_only_observations(app):
    with app.app_context():
        db.session.query(DailyObservation).update(
            {DailyObservation.source: "synthetic"},
            synchronize_session=False,
        )
        db.session.commit()

        with pytest.raises(ValueError, match="No real IMERG observations"):
            train_and_persist()
        assert load_active_model(app.config["MODELS_DIR"]) is None


def test_inference_frame_features_match_training_columns():
    frame = generate_test_rainfall(
        date(2018, 1, 1), date(2025, 12, 31), seed=3
    )
    observations = frame.assign(coverage_pct=100.0)
    inference = build_inference_frame(observations)
    assert inference is not None
    assert tuple(inference.columns) == FEATURE_COLUMNS
    assert not inference.isna().to_numpy().any()
