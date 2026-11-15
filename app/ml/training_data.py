"""Build weakly labeled, season-aware datasets from real IMERG observations."""

from __future__ import annotations

from math import floor

import numpy as np
import pandas as pd

from ..config import Config
from .onset import detect_onsets

FEATURE_COLUMNS = (
    "month",
    "season_day",
    "day_of_year_sin",
    "day_of_year_cos",
    "rain_3d_mm",
    "rain_7d_mm",
    "rain_14d_mm",
    "rain_30d_mm",
    "dry_days_7d",
    "coverage_30d_pct",
)
TARGET_COLUMN = "effective_onset_next_21d"
PREDICTION_HORIZON_DAYS = 21
MIN_SEASONS_FOR_SPLIT = 5


def _prepare_observations(
    observations: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.DatetimeIndex]:
    """Validate observation rows and return aligned daily series."""
    required = {"day", "precip_mm", "coverage_pct"}
    missing_columns = required.difference(observations.columns)
    if missing_columns:
        raise ValueError(
            "Missing observation columns: " + ", ".join(sorted(missing_columns))
        )
    if observations.empty:
        raise ValueError("No IMERG observations were provided.")

    frame = observations.loc[:, ["day", "precip_mm", "coverage_pct"]].copy()
    frame["day"] = pd.to_datetime(frame["day"], errors="raise").dt.normalize()
    if frame["day"].duplicated().any():
        raise ValueError("IMERG observations must contain at most one row per day.")

    frame = frame.sort_values("day")
    date_index = pd.date_range(frame["day"].min(), frame["day"].max(), freq="D")
    precipitation = pd.Series(
        frame["precip_mm"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(frame["day"]),
    ).reindex(date_index)
    coverage = pd.Series(
        frame["coverage_pct"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(frame["day"]),
    ).reindex(date_index)
    return precipitation, coverage, date_index


def compute_daily_features(observations: pd.DataFrame) -> pd.DataFrame:
    """Return the per-day ML features (without target) over the full series.

    The same rolling windows used to build training examples are computed
    once over the whole series, so training and inference stay consistent.
    """
    precipitation, coverage, date_index = _prepare_observations(observations)

    rolling_rain = {
        window: precipitation.rolling(window, min_periods=window).sum()
        for window in (3, 7, 14, 30)
    }
    dry_days_7d = precipitation.rolling(7, min_periods=7).apply(
        lambda values: float(np.count_nonzero(values < Config.DECISION_DRY_DAY_MM)),
        raw=True,
    )
    coverage_30d = coverage.rolling(30, min_periods=30).mean()
    angle = 2 * np.pi * date_index.day_of_year / 365.25
    return pd.DataFrame(
        {
            "month": date_index.month,
            "day_of_year_sin": np.sin(angle),
            "day_of_year_cos": np.cos(angle),
            "rain_3d_mm": rolling_rain[3],
            "rain_7d_mm": rolling_rain[7],
            "rain_14d_mm": rolling_rain[14],
            "rain_30d_mm": rolling_rain[30],
            "dry_days_7d": dry_days_7d,
            "coverage_30d_pct": coverage_30d,
        },
        index=date_index,
    )


def build_inference_frame(
    observations: pd.DataFrame,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame | None:
    """Build a single-row feature frame for model inference.

    Uses the latest available observation day (or ``as_of``). Returns None
    when the day has missing values, so callers can fall back to the
    heuristic decision engine.
    """
    features = compute_daily_features(observations)
    if features.empty:
        return None
    day = as_of if as_of is not None else features.index.max()
    if day not in features.index:
        return None
    season_year = (
        day.year
        if day.month >= Config.SEASON_START_MONTH
        else day.year - 1
    )
    row = features.loc[[day]].copy()
    row["season_day"] = (
        day - pd.Timestamp(season_year, Config.SEASON_START_MONTH, 1)
    ).days
    return row.loc[:, FEATURE_COLUMNS]


def _complete_season_windows(precipitation, coverage, date_index):
    """Yield complete rainy seasons as (year, start, end, values, coverage).

    A season is complete when daily precipitation and coverage exist from 29
    days before October 1 through 21 days after March 31, so onset detection
    and its 21-day label window never cross a data gap.
    """
    for season_year in range(date_index.min().year, date_index.max().year + 1):
        season_start = pd.Timestamp(season_year, 10, 1)
        season_end = pd.Timestamp(season_year + 1, 3, 31)
        support_start = season_start - pd.Timedelta(days=29)
        support_end = season_end + pd.Timedelta(
            days=Config.ONSET_HORIZON_DAYS
        )
        if support_start < date_index.min() or support_end > date_index.max():
            continue

        support_index = pd.date_range(support_start, support_end, freq="D")
        season_values = precipitation.reindex(support_index)
        season_coverage = coverage.reindex(support_index)
        if season_values.isna().any() or season_coverage.isna().any():
            continue
        yield season_year, season_start, season_end, season_values, season_coverage


def complete_seasons(observations: pd.DataFrame) -> list[int]:
    """Rainy-season years that carry complete daily coverage for training."""
    precipitation, coverage, date_index = _prepare_observations(observations)
    return [
        season_year
        for season_year, *_ in _complete_season_windows(
            precipitation, coverage, date_index
        )
    ]


def build_onset_dataset(observations: pd.DataFrame) -> pd.DataFrame:
    """Create daily examples labeled by the existing effective-onset rule.

    Only complete rainy seasons are included. Features use observations up to
    each date; the target indicates an effective onset in the following 21 days.
    """
    precipitation, coverage, date_index = _prepare_observations(observations)
    features = compute_daily_features(observations)

    examples: list[dict] = []

    for (
        season_year,
        season_start,
        season_end,
        season_values,
        _season_coverage,
    ) in _complete_season_windows(precipitation, coverage, date_index):
        events = detect_onsets(
            season_values,
            season_start_month=Config.SEASON_START_MONTH,
            season_start_day=Config.SEASON_START_DAY,
            window=Config.ONSET_WINDOW_DAYS,
            threshold_mm=Config.ONSET_THRESHOLD_MM,
            dry_spell_days=Config.ONSET_DRY_SPELL_DAYS,
            horizon_days=Config.ONSET_HORIZON_DAYS,
            dry_day_mm=Config.DECISION_DRY_DAY_MM,
        )
        effective_onsets = [
            pd.Timestamp(event.onset_date)
            for event in events
            if not event.false_onset
            and season_start.date() <= event.onset_date <= season_end.date()
        ]

        last_sample_day = season_end - pd.Timedelta(
            days=PREDICTION_HORIZON_DAYS
        )
        for day in pd.date_range(season_start, last_sample_day, freq="D"):
            day_features = features.loc[day]
            examples.append(
                {
                    "day": day.date().isoformat(),
                    "season_year": season_year,
                    "month": int(day_features["month"]),
                    "season_day": (day - season_start).days,
                    "day_of_year_sin": float(day_features["day_of_year_sin"]),
                    "day_of_year_cos": float(day_features["day_of_year_cos"]),
                    "rain_3d_mm": float(day_features["rain_3d_mm"]),
                    "rain_7d_mm": float(day_features["rain_7d_mm"]),
                    "rain_14d_mm": float(day_features["rain_14d_mm"]),
                    "rain_30d_mm": float(day_features["rain_30d_mm"]),
                    "dry_days_7d": float(day_features["dry_days_7d"]),
                    "coverage_30d_pct": float(day_features["coverage_30d_pct"]),
                    TARGET_COLUMN: int(
                        any(
                            day < onset <= day + pd.Timedelta(
                                days=PREDICTION_HORIZON_DAYS
                            )
                            for onset in effective_onsets
                        )
                    ),
                }
            )

    if not examples:
        raise ValueError(
            "No complete rainy seasons found. Each season needs daily IMERG "
            "coverage from 29 days before October 1 through 21 days after "
            "March 31."
        )
    return pd.DataFrame(examples)


def split_by_season(
    examples: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Split chronologically by rainy season to prevent temporal leakage."""
    if "season_year" not in examples or examples.empty:
        raise ValueError("A non-empty dataset with season_year is required.")

    seasons = sorted(int(year) for year in examples["season_year"].unique())
    if len(seasons) < MIN_SEASONS_FOR_SPLIT:
        raise ValueError(
            f"At least {MIN_SEASONS_FOR_SPLIT} complete seasons are required "
            f"for train/validation/test splits; found {len(seasons)}."
        )

    train_count = max(1, floor(len(seasons) * 0.6))
    validation_count = max(1, floor(len(seasons) * 0.2))
    if train_count + validation_count >= len(seasons):
        train_count = len(seasons) - 2
        validation_count = 1

    boundaries = (
        seasons[:train_count],
        seasons[train_count : train_count + validation_count],
        seasons[train_count + validation_count :],
    )
    return {
        name: examples[examples["season_year"].isin(years)].copy()
        for name, years in zip(
            ("train", "validation", "test"), boundaries, strict=True
        )
    }
