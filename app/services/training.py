"""Train the onset classifier from stored observations and persist it."""

from __future__ import annotations

from flask import current_app

from ..ml.classifier import train_onset_classifier
from ..ml.persistence import MODEL_VERSION, load_active_model, save_model
from ..ml.training_data import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    build_onset_dataset,
    complete_seasons,
    split_by_season,
)
from .series_service import load_daily

_REAL_OBSERVATION_SOURCES = frozenset(
    {"imerg_early_daily", "imerg_final_daily"}
)


def _metadata(data_status_value: str, metrics: dict, splits: dict) -> dict:
    return {
        "algorithm": "sklearn.ensemble.RandomForestClassifier",
        "target": TARGET_COLUMN,
        "feature_columns": list(FEATURE_COLUMNS),
        "data_status": data_status_value,
        "split_method": "chronological by rainy season (60/20/20)",
        "splits": {
            name: {"rows": int(len(frame))}
            for name, frame in splits.items()
        },
        "metrics": metrics,
    }


def train_and_persist() -> dict:
    """Train only on real IMERG observations and save the model.

    Raises ValueError when there is not enough complete-season data; callers
    must keep the heuristic fallback active in that case.
    """
    frame = load_daily()
    frame = frame.loc[frame["source"].isin(_REAL_OBSERVATION_SOURCES)].copy()
    if frame.empty:
        raise ValueError("No real IMERG observations are available for training.")

    dataset = build_onset_dataset(frame)
    splits = split_by_season(dataset)
    model, metrics = train_onset_classifier(splits)
    metadata = _metadata("real", metrics, splits)
    record = save_model(model, metadata, current_app.config["MODELS_DIR"])
    return record


def ensure_trained_model() -> dict | None:
    """Keep only a model trained from real IMERG observations."""
    models_dir = current_app.config["MODELS_DIR"]
    existing = load_active_model(models_dir)
    if existing is not None and existing[1].get("data_status") == "real":
        return existing[1]
    return train_and_persist()


def training_season_span() -> dict | None:
    """Rainy-season range the classifier is trained on (complete seasons)."""
    frame = load_daily()
    frame = frame.loc[frame["source"].isin(_REAL_OBSERVATION_SOURCES)]
    if frame.empty:
        return None
    years = complete_seasons(frame)
    if not years:
        return None
    first, last = years[0], years[-1]
    return {
        "count": len(years),
        "start": first,
        "end": last,
        "range": f"{first}/{(first + 1) % 100:02d}–{last}/{(last + 1) % 100:02d}",
    }


def active_model_info() -> dict | None:
    """Public summary of the currently persisted model, if any."""
    existing = load_active_model(current_app.config["MODELS_DIR"])
    if existing is None:
        return None
    model, metadata = existing
    return {
        "version": metadata.get("version", MODEL_VERSION),
        "saved_at": metadata.get("saved_at"),
        "data_status": metadata.get("data_status"),
        "splits": metadata.get("splits"),
        "metrics": metadata.get("metrics"),
    }
