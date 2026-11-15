"""30-day planting plan built from the forecast and the climatology."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..config import Config
from ..i18n import translate
from .decision_weather import (
    WEATHER_ICONS,
    _climate_condition,
    _weather_condition,
)

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _same_day_values(series: pd.Series, target: date) -> np.ndarray:
    mask = (series.index.month == target.month) & (series.index.day == target.day)
    values = series[mask].to_numpy(dtype=float)
    values = values[~np.isnan(values)]
    if values.size == 0 and target.month == 2 and target.day == 29:
        return _same_day_values(series, date(2001, 2, 28))
    return values


def _climate_daily_probability(
    series: pd.Series,
    target: date,
    wet_mm: float,
) -> float | None:
    values = _same_day_values(series, target)
    if values.size == 0:
        return None
    return float(np.count_nonzero(values >= wet_mm) / values.size)


def _climate_onset_probability(
    series: pd.Series,
    target: date,
    window: int,
    threshold_mm: float,
) -> float | None:
    years = sorted({int(year) for year in series.index.year})
    hits = 0
    total = 0
    for year in years:
        try:
            start = date(year, target.month, target.day)
        except ValueError:
            continue
        dates = pd.to_datetime(
            [start + timedelta(days=offset) for offset in range(window)]
        )
        values = series.reindex(dates).to_numpy(dtype=float)
        if values.size == 0 or np.isnan(values).any():
            continue
        total += 1
        if float(np.nansum(values)) >= threshold_mm:
            hits += 1
    if total == 0:
        return None
    return hits / total


def _forecast_window_mm(
    forecast_by_date: dict[str, dict],
    target: date,
    window: int,
) -> float | None:
    values = []
    for offset in range(window):
        row = forecast_by_date.get((target + timedelta(days=offset)).isoformat())
        if row is None or row.get("precip_mm") is None:
            return None
        values.append(float(row["precip_mm"]))
    return sum(values)


def _plan_action(
    state: str,
    offset: int,
    days_to_plant: int | None,
    phase: str,
    forecast_window_mm: float | None,
) -> str:
    if phase != "forecast":
        return "monitor"

    if state == "PLANT_NOW" and offset <= 2:
        return "plant"

    if state == "PLANT_IN_DAYS":
        if days_to_plant is None:
            return "prepare" if offset <= 2 else "monitor"
        if days_to_plant <= offset <= days_to_plant + 2:
            return "plant"
        if days_to_plant - 3 <= offset < days_to_plant:
            return "prepare"
        if offset < days_to_plant:
            return "wait"
        return "monitor"

    if state == "HIGH_RISK":
        return "wait"

    if (
        forecast_window_mm is not None
        and forecast_window_mm >= Config.ONSET_THRESHOLD_MM
        and state != "WAIT"
    ):
        return "prepare"

    if state == "WAIT":
        return "wait"

    return "monitor"


def _plan_date(reference_day: date, offset: int | None) -> str | None:
    if offset is None:
        return None
    return (reference_day + timedelta(days=int(offset))).strftime("%d/%m")


def _plan_summary(
    series: pd.Series,
    forecast_info: dict | None,
    reference_day: date,
    state: str,
    days_to_plant: int | None,
    data_stale: bool,
    lang: str,
) -> dict:
    forecast_rows = sorted(
        (
            row
            for row in (forecast_info or {}).get("rows", [])
            if row.get("date") and row["date"] >= reference_day.isoformat()
        ),
        key=lambda row: row["date"],
    )
    forecast_by_date = {row["date"]: row for row in forecast_rows}

    days = []
    forecast_days = 0
    climate_days = 0
    for offset in range(30):
        target = reference_day + timedelta(days=offset)
        row = forecast_by_date.get(target.isoformat())
        phase = "forecast" if row is not None else "climate"

        if row is not None:
            forecast_days += 1
            condition = _weather_condition(row)
            probability_pct = row.get("probability_pct")
            probability_pct = (
                round(float(probability_pct))
                if probability_pct is not None
                else None
            )
            rain_mm = row.get("precip_mm")
            rain_mm = round(float(rain_mm), 1) if rain_mm is not None else None
            onset_probability_pct = None
        else:
            climate_days += 1
            daily_probability = _climate_daily_probability(
                series,
                target,
                Config.DECISION_DRY_DAY_MM,
            )
            probability_pct = (
                round(daily_probability * 100)
                if daily_probability is not None
                else None
            )
            condition = _climate_condition(probability_pct)
            rain_mm = None
            onset_probability = _climate_onset_probability(
                series,
                target,
                Config.ONSET_WINDOW_DAYS,
                Config.ONSET_THRESHOLD_MM,
            )
            onset_probability_pct = (
                round(onset_probability * 100)
                if onset_probability is not None
                else None
            )

        forecast_window_mm = _forecast_window_mm(
            forecast_by_date,
            target,
            Config.ONSET_WINDOW_DAYS,
        )
        action = _plan_action(
            state,
            offset,
            days_to_plant,
            phase,
            forecast_window_mm,
        )
        days.append(
            {
                "date": target.isoformat(),
                "label": target.strftime("%d/%m"),
                "weekday": translate(
                    f"forecast.weekday.{_WEEKDAY_KEYS[target.weekday()]}",
                    lang,
                ),
                "phase": phase,
                "condition": condition,
                "icon": WEATHER_ICONS[condition],
                "weather_label": translate(
                    f"forecast.{condition.replace('-', '_')}",
                    lang,
                ),
                "probability_pct": probability_pct,
                "onset_probability_pct": onset_probability_pct,
                "rain_mm": rain_mm,
                "action": action,
                "is_today": offset == 0,
            }
        )

    best_window_start = None
    best_window_end = None
    next_check = None
    if not data_stale:
        if state == "PLANT_NOW":
            best_window_start = 0
            best_window_end = min(2, max(0, forecast_days - 1))
            next_check = 3
        elif state == "PLANT_IN_DAYS" and days_to_plant is not None:
            best_window_start = max(0, min(days_to_plant, 29))
            best_window_end = min(29, best_window_start + 2)
            next_check = max(1, best_window_start - 1)
        elif state == "HIGH_RISK":
            next_check = 3
        else:
            next_check = 7

    return {
        "days": days,
        "forecast_days": forecast_days,
        "climate_days": climate_days,
        "best_window_start": _plan_date(reference_day, best_window_start),
        "best_window_end": _plan_date(reference_day, best_window_end),
        "next_check": _plan_date(reference_day, next_check),
        "climate_years": int(series.index.year.nunique()),
        "has_forecast": forecast_days > 0,
        "stale": data_stale,
    }
