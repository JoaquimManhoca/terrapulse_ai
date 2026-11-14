"""Classifier training and evaluation for the effective-onset proxy target."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from .training_data import FEATURE_COLUMNS, TARGET_COLUMN


def train_onset_classifier(
    splits: Mapping[str, pd.DataFrame],
) -> tuple[RandomForestClassifier, dict[str, dict[str, float | int | None]]]:
    """Train on the training seasons and report validation/test metrics."""
    for split_name in ("train", "validation", "test"):
        if split_name not in splits or splits[split_name].empty:
            raise ValueError(f"The {split_name} split must not be empty.")
        missing = set(FEATURE_COLUMNS + (TARGET_COLUMN,)).difference(
            splits[split_name].columns
        )
        if missing:
            raise ValueError(
                f"The {split_name} split is missing columns: "
                + ", ".join(sorted(missing))
            )

    training = splits["train"]
    if training[TARGET_COLUMN].nunique() < 2:
        raise ValueError("The training split must contain both target classes.")

    model = RandomForestClassifier(
        n_estimators=150,
        max_depth=8,
        min_samples_leaf=5,
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=1,
    )
    model.fit(training.loc[:, FEATURE_COLUMNS], training[TARGET_COLUMN])

    metrics = {
        name: _evaluate(model, frame)
        for name, frame in splits.items()
        if name in {"validation", "test"}
    }
    return model, metrics


def _evaluate(
    model: RandomForestClassifier,
    frame: pd.DataFrame,
) -> dict[str, float | int | None]:
    expected = frame[TARGET_COLUMN]
    predicted = model.predict(frame.loc[:, FEATURE_COLUMNS])
    probabilities = model.predict_proba(frame.loc[:, FEATURE_COLUMNS])[:, 1]
    return {
        "rows": int(len(frame)),
        "positive_labels": int(expected.sum()),
        "negative_labels": int((expected == 0).sum()),
        "accuracy": float(accuracy_score(expected, predicted)),
        "precision": float(precision_score(expected, predicted, zero_division=0)),
        "recall": float(recall_score(expected, predicted, zero_division=0)),
        "f1": float(f1_score(expected, predicted, zero_division=0)),
        "roc_auc": (
            float(roc_auc_score(expected, probabilities))
            if expected.nunique() == 2
            else None
        ),
    }
