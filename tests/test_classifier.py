from __future__ import annotations

import pandas as pd
import pytest

from app.ml.classifier import train_onset_classifier
from app.ml.training_data import build_onset_dataset, split_by_season


def _complete_rainfall_seasons(count: int = 7) -> pd.DataFrame:
    first_year = 2015
    last_year = first_year + count - 1
    days = pd.date_range(
        f"{first_year}-09-02",
        f"{last_year + 1}-04-21",
        freq="D",
    )
    precipitation = pd.Series(0.0, index=days)
    for year in range(first_year, last_year + 1):
        precipitation.loc[f"{year}-11-01":f"{year}-11-03"] = 10.0
        precipitation.loc[f"{year}-11-04":f"{year}-11-24"] = 2.0
    return pd.DataFrame(
        {
            "day": days,
            "precip_mm": precipitation.to_numpy(),
            "coverage_pct": 100.0,
        }
    )


def test_classifier_trains_and_reports_holdout_metrics():
    dataset = build_onset_dataset(_complete_rainfall_seasons())
    splits = split_by_season(dataset)

    model, metrics = train_onset_classifier(splits)

    assert model.n_features_in_ > 0
    assert set(metrics) == {"validation", "test"}
    assert metrics["test"]["rows"] == len(splits["test"])
    assert 0 <= metrics["test"]["accuracy"] <= 1


def test_classifier_rejects_training_split_with_one_class():
    dataset = build_onset_dataset(_complete_rainfall_seasons())
    splits = split_by_season(dataset)
    splits["train"] = splits["train"].copy()
    splits["train"].loc[:, "effective_onset_next_21d"] = 0

    with pytest.raises(ValueError, match="both target classes"):
        train_onset_classifier(splits)
