"""Rainy-season onset detection.

Two complementary tools:

* ``detect_onsets`` -> first candidate onset of each season, used for climatology
  and for the historical false-onset rate.
* ``latest_wet_event`` -> most recent wet window, used to judge whether a rain
  episode that already started is at risk of failing (false onset).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OnsetEvent:
    onset_date: date
    window_mm: float
    dry_streak_after: int
    false_onset: bool

    def to_dict(self) -> dict:
        return {
            "onset_date": self.onset_date.isoformat(),
            "window_mm": round(self.window_mm, 1),
            "dry_streak_after": self.dry_streak_after,
            "false_onset": self.false_onset,
        }


def as_daily_series(days, values) -> pd.Series:
    """Build a clean, sorted daily Series from dates and values."""
    index = pd.to_datetime(list(days))
    series = pd.Series(np.asarray(values, dtype=float), index=index)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series


def _max_dry_streak(window: pd.Series, dry_day_mm: float) -> int:
    """Longest run of consecutive dry days inside the window.

    Missing days are treated as unknown (not dry) so they break a streak
    instead of inflating it.
    """
    if window.empty:
        return 0
    best = 0
    streak = 0
    for value in window.fillna(999.0).to_numpy(dtype=float):
        if value < dry_day_mm:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def detect_onsets(
    series: pd.Series,
    *,
    season_start_month: int = 10,
    season_start_day: int = 1,
    window: int = 3,
    threshold_mm: float = 20.0,
    dry_spell_days: int = 7,
    horizon_days: int = 21,
    dry_day_mm: float = 1.0,
) -> list[OnsetEvent]:
    """Return the first candidate onset per rainy season.

    An onset is the end of the first ``window``-day period whose total rain
    reaches ``threshold_mm`` after the season start. It is labelled a false
    onset when ``dry_spell_days`` or more dry days follow within ``horizon_days``.
    """
    if series is None or series.empty:
        return []

    series = series.sort_index()
    onsets: list[OnsetEvent] = []
    start_year = int(series.index.min().year)
    end_year = int(series.index.max().year)

    for year in range(start_year, end_year + 1):
        season_start = pd.Timestamp(year=year, month=season_start_month, day=season_start_day)
        season_end = pd.Timestamp(year=year + 1, month=3, day=31)
        if season_start > series.index.max():
            break
        season = series.loc[season_start:season_end]
        if len(season) < window:
            continue

        rolling = season.rolling(window=window, min_periods=window).sum()
        candidates = rolling[rolling >= threshold_mm]
        if candidates.empty:
            continue

        onset_ts = candidates.index[0]
        window_start = onset_ts - pd.Timedelta(days=window - 1)
        if window_start < season.index.min():
            continue

        after = series.loc[onset_ts + pd.Timedelta(days=1): onset_ts + pd.Timedelta(days=horizon_days)]
        dry_streak = _max_dry_streak(after, dry_day_mm)
        onsets.append(
            OnsetEvent(
                onset_date=onset_ts.date(),
                window_mm=float(rolling.loc[onset_ts]),
                dry_streak_after=dry_streak,
                false_onset=dry_streak >= dry_spell_days,
            )
        )

    return onsets


def latest_wet_event(
    series: pd.Series,
    *,
    lookback_days: int = 30,
    window: int = 3,
    threshold_mm: float = 20.0,
    dry_spell_days: int = 7,
    horizon_days: int = 14,
    dry_day_mm: float = 1.0,
) -> OnsetEvent | None:
    """Return the most recent wet window and whether it is drying out."""
    if series is None or series.empty:
        return None

    series = series.sort_index()
    end = series.index.max()
    start = end - pd.Timedelta(days=lookback_days)
    recent = series.loc[start:end]
    if len(recent) < window:
        return None

    rolling = recent.rolling(window=window, min_periods=window).sum()
    candidates = rolling[rolling >= threshold_mm]
    if candidates.empty:
        return None

    onset_ts = candidates.index[-1]
    after = series.loc[onset_ts + pd.Timedelta(days=1): onset_ts + pd.Timedelta(days=horizon_days)]
    dry_streak = _max_dry_streak(after, dry_day_mm)
    return OnsetEvent(
        onset_date=onset_ts.date(),
        window_mm=float(rolling.loc[onset_ts]),
        dry_streak_after=dry_streak,
        false_onset=dry_streak >= dry_spell_days,
    )
