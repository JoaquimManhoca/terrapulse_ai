"""Access to the cleaned daily rainfall series stored in SQLite."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ..extensions import db
from ..models import DailyObservation


def load_daily(start: date | None = None, end: date | None = None) -> pd.DataFrame:
    query = db.session.query(
        DailyObservation.day,
        DailyObservation.precip_mm,
        DailyObservation.coverage_pct,
        DailyObservation.source,
    )
    if start is not None:
        query = query.filter(DailyObservation.day >= start)
    if end is not None:
        query = query.filter(DailyObservation.day <= end)

    rows = query.order_by(DailyObservation.day).all()
    frame = pd.DataFrame(rows, columns=["day", "precip_mm", "coverage_pct", "source"])
    if not frame.empty:
        frame["day"] = pd.to_datetime(frame["day"]).dt.date
    return frame


def daily_series(start: date | None = None, end: date | None = None) -> pd.Series:
    frame = load_daily(start, end)
    if frame.empty:
        return pd.Series(dtype=float)
    series = pd.Series(
        frame["precip_mm"].to_numpy(dtype=float),
        index=pd.to_datetime(frame["day"]),
    )
    return series.sort_index()


def _peak(values) -> float:
    if len(values) == 0:
        return 0.0
    finite = values[~np.isnan(values)]
    if finite.size == 0:
        return 0.0
    return max(float(np.nanmax(finite)), 1.0)


def last_updated() -> str | None:
    series = daily_series()
    if series.empty:
        return None
    return series.index.max().strftime("%d/%m/%Y")


def data_status() -> str:
    rows = db.session.query(DailyObservation.source).distinct().all()
    sources = {row[0] for row in rows if row[0]}
    if not sources:
        return "empty"
    if sources == {"synthetic"}:
        return "synthetic"
    if "synthetic" in sources:
        return "mixed"
    return "real"


def recent_days(n: int = 14) -> list[dict]:
    series = daily_series()
    if series.empty:
        return []
    tail = series.tail(n)
    values = tail.to_numpy(dtype=float)
    peak = _peak(values)
    result = []
    for ts, value in tail.items():
        amount = 0.0 if pd.isna(value) else float(value)
        result.append(
            {
                "date": ts.strftime("%d/%m"),
                "label": ts.strftime("%d/%m/%Y"),
                "precip_mm": round(amount, 1),
                "height": max(2, round(amount / peak * 100)),
            }
        )
    return result


def monthly_totals(months: int = 24) -> list[dict]:
    series = daily_series()
    if series.empty:
        return []
    monthly = series.resample("MS").sum(min_count=1).tail(months)
    values = monthly.to_numpy(dtype=float)
    peak = _peak(values)
    result = []
    for ts, value in monthly.items():
        amount = None if pd.isna(value) else round(float(value), 1)
        result.append(
            {
                "month": ts.strftime("%m/%Y"),
                "label": ts.strftime("%m/%y"),
                "precip_mm": amount,
                "height": 0 if amount is None else max(2, round(amount / peak * 100)),
            }
        )
    return result


def yearly_totals() -> list[dict]:
    series = daily_series()
    if series.empty:
        return []
    yearly = series.resample("YS").sum(min_count=1)
    values = yearly.to_numpy(dtype=float)
    peak = _peak(values)
    result = []
    for ts, value in yearly.items():
        amount = None if pd.isna(value) else round(float(value), 1)
        result.append(
            {
                "year": ts.strftime("%Y"),
                "precip_mm": amount,
                "height": 0 if amount is None else max(2, round(amount / peak * 100)),
            }
        )
    return result


SEASON_MONTHS = ((10, "Out"), (11, "Nov"), (12, "Dez"), (1, "Jan"), (2, "Fev"), (3, "Mar"))


def season_monthly_totals() -> list[dict]:
    """Per rainy season: Oct-Mar monthly totals with bar heights.

    Each row: {season, label, total_mm, days, real_pct, chip, months}.
    ``months`` carries the same detail level as the monthly chart.
    """
    from .season_series import seasonal_totals

    seasons = seasonal_totals()
    if not seasons:
        return []

    series = daily_series()
    monthly = series.resample("MS").sum(min_count=1)
    lookup: dict[tuple[int, int], float] = {
        (ts.year, ts.month): float(value)
        for ts, value in monthly.items()
        if value == value
    }

    result = []
    for item in seasons:
        season = int(item["season"])
        months = []
        for month, label in SEASON_MONTHS:
            year = season if month >= 10 else season + 1
            total = round(lookup.get((year, month), 0.0), 1)
            months.append({"label": label, "total_mm": total})
        peak = max((m["total_mm"] for m in months), default=1.0) or 1.0
        for entry in months:
            entry["height"] = max(2, round(entry["total_mm"] / peak * 100))

        label = f"{season}/{(season + 1) % 100:02d}"
        real_pct = float(item["real_pct"])
        chip = "real" if real_pct >= 90 else ("partial" if real_pct >= 30 else "synthetic")
        result.append(
            {
                "season": season,
                "label": label,
                "total_mm": item["total_mm"],
                "days": item["days"],
                "real_pct": real_pct,
                "chip": chip,
                "months": months,
            }
        )
    return result
