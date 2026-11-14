"""Persistence for the trained onset classifier.

The model and its metadata travel together in a single joblib file under
``data/models`` so the served decision engine always knows the exact
version, features and holdout metrics it is using.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import joblib
from sklearn.ensemble import RandomForestClassifier

MODEL_VERSION = "onset-rf-v1"
MODEL_FILENAME = "onset_rf.joblib"


def model_path(models_dir: Path | str) -> Path:
    return Path(models_dir) / MODEL_FILENAME


def save_model(
    model: RandomForestClassifier,
    metadata: dict,
    models_dir: Path | str,
) -> dict:
    """Persist model + metadata atomically and return the stored metadata."""
    directory = Path(models_dir)
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "version": MODEL_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }
    target = model_path(models_dir)
    temp = target.with_suffix(".joblib.tmp")
    joblib.dump({"model": model, "metadata": record}, temp)
    temp.replace(target)
    return record


def load_active_model(
    models_dir: Path | str,
) -> tuple[RandomForestClassifier, dict] | None:
    """Return (model, metadata) when a trained model is available."""
    target = model_path(models_dir)
    if not target.exists():
        return None
    try:
        bundle = joblib.load(target)
    except Exception:
        return None
    model = bundle.get("model")
    metadata = bundle.get("metadata", {})
    if model is None:
        return None
    return model, metadata
