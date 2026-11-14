"""Aggregation of the daily rainfall series into rainy-season series."""

from __future__ import annotations

import pandas as pd

from ..extensions import db
from ..models import DailyObservation

SYNTHETIC_SOURCES = {"synthetic"}


def _season_year(day: pd.Timestamp) -> int | None:
    """Rainy season that a day belongs to (Oct-Dec -> year, Jan-Mar -> year-1)."""
    if day.month >= 10:
        return day.year
    if day.month <= 3:
        return day.year - 1
    return None


def seasonal_totals() -> list[dict]:
    """Total precipitation per rainy season (Oct 1 - Mar 31), oldest first."""
    rows = db.session.query(
        DailyObservation.day, DailyObservation.precip_mm, DailyObservation.source
    ).order_by(DailyObservation.day).all()
    if not rows:
        return []

    frame = pd.DataFrame(rows, columns=["day", "precip_mm", "source"])
    frame["day"] = pd.to_datetime(frame["day"])
    frame = frame.dropna(subset=["precip_mm"])
    frame["season"] = frame["day"].map(_season_year)
    frame = frame.dropna(subset=["season"])

    grouped = frame.groupby("season")
    result = []
    for season, group in grouped:
        real_count = int((~group["source"].isin(SYNTHETIC_SOURCES)).sum())
        result.append(
            {
                "season": int(season),
                "total_mm": round(float(group["precip_mm"].sum()), 1),
                "days": int(len(group)),
                "real_pct": round(100.0 * real_count / len(group), 1),
            }
        )
    return result


def recent_seasons(limit: int = 10) -> list[dict]:
    """The most recent rainy seasons, oldest first, with real-data share."""
    seasons = seasonal_totals()
    result = []
    for item in seasons[-limit:]:
        label = f"{item['season']}/{(item['season'] + 1) % 100:02d}"
        if item["real_pct"] >= 90:
            chip = "real"
        elif item["real_pct"] >= 30:
            chip = "partial"
        else:
            chip = "synthetic"
        result.append(
            {
                "season": item["season"],
                "label": label,
                "total_mm": item["total_mm"],
                "days": item["days"],
                "real_pct": item["real_pct"],
                "chip": chip,
            }
        )
    peak = max((r["total_mm"] for r in result), default=1.0) or 1.0
    for row in result:
        row["width_pct"] = max(3, round(100.0 * row["total_mm"] / peak))
    return result


def monthly_totals_by_month(month: int) -> list[dict]:
    """Total precipitation of one calendar month, per season (e.g. November)."""
    rows = db.session.query(
        DailyObservation.day, DailyObservation.precip_mm, DailyObservation.source
    ).order_by(DailyObservation.day).all()
    if not rows:
        return []

    frame = pd.DataFrame(rows, columns=["day", "precip_mm", "source"])
    frame["day"] = pd.to_datetime(frame["day"])
    frame = frame.dropna(subset=["precip_mm"])
    frame["season"] = frame["day"].map(_season_year)
    frame = frame[frame["day"].dt.month == month].dropna(subset=["season"])

    result = []
    for season, group in frame.groupby("season"):
        real_count = int((~group["source"].isin(SYNTHETIC_SOURCES)).sum())
        result.append(
            {
                "season": int(season),
                "total_mm": round(float(group["precip_mm"].sum()), 1),
                "days": int(len(group)),
                "real_pct": round(100.0 * real_count / len(group), 1),
            }
        )
    return result
