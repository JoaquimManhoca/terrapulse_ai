from __future__ import annotations

import pandas as pd
import pytest

from app.ml.training_data import (
    TARGET_COLUMN,
    build_onset_dataset,
    split_by_season,
)


def _rainfall_observations(seasons: int = 7) -> pd.DataFrame:
    first_year = 2015
    last_year = first_year + seasons - 1
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


def test_build_onset_dataset_labels_future_effective_onset():
    dataset = build_onset_dataset(_rainfall_observations())

    before_onset = dataset[dataset["day"] == "2015-11-01"].iloc[0]
    assert before_onset[TARGET_COLUMN] == 1
    assert dataset[TARGET_COLUMN].isin([0, 1]).all()
    assert dataset["season_year"].nunique() == 7
    assert not dataset.isna().any().any()


def test_split_by_season_is_chronological_and_disjoint():
    dataset = build_onset_dataset(_rainfall_observations())

    splits = split_by_season(dataset)
    train_seasons = set(splits["train"]["season_year"])
    validation_seasons = set(splits["validation"]["season_year"])
    test_seasons = set(splits["test"]["season_year"])

    assert train_seasons.isdisjoint(validation_seasons)
    assert train_seasons.isdisjoint(test_seasons)
    assert validation_seasons.isdisjoint(test_seasons)
    assert max(train_seasons) < min(validation_seasons)
    assert max(validation_seasons) < min(test_seasons)
    assert sum(map(len, splits.values())) == len(dataset)


def test_build_onset_dataset_rejects_incomplete_season_history():
    observations = _rainfall_observations()
    short_history = observations[
        observations["day"].between("2015-12-01", "2016-01-01")
    ]

    with pytest.raises(ValueError, match="No complete rainy seasons"):
        build_onset_dataset(short_history)


def test_split_by_season_requires_multiple_complete_seasons():
    examples = pd.DataFrame({"season_year": [2020, 2021, 2022, 2023]})

    with pytest.raises(ValueError, match="At least 5 complete seasons"):
        split_by_season(examples)
