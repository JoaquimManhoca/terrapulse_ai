"""Short-term forecast summary for the decision engine."""

from __future__ import annotations

from datetime import date

from ..config import Config
from ..i18n import translate
from .decision_weather import WEATHER_ICONS, _weather_condition

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _forecast_summary(
    forecast: dict | None,
    reference_day: date,
    lang: str = "pt",
) -> dict | None:
    if not forecast:
        return None
    future = [
        row
        for row in forecast.get("rows", [])
        if (row.get("date") or "") >= reference_day.isoformat()
    ]
    future = future[:16]
    rain_7d = sum((row.get("precip_mm") or 0.0) for row in future[:7])
    values = [row.get("precip_mm") or 0.0 for row in future]
    days_to_onset = None
    last_start = len(values) - Config.ONSET_WINDOW_DAYS
    for index in range(max(0, last_start + 1)):
        if sum(values[index:index + Config.ONSET_WINDOW_DAYS]) >= Config.ONSET_THRESHOLD_MM:
            days_to_onset = index
            break

    daily = []
    reference = reference_day.isoformat()
    current_rows = sorted(
        (
            row
            for row in forecast.get("rows", [])
            if row.get("date") and row["date"] >= reference
        ),
        key=lambda row: row["date"],
    )
    weekday_keys = (
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    )
    for row in current_rows[:7]:
        day = date.fromisoformat(row["date"])
        weekday = translate(f"forecast.weekday.{weekday_keys[day.weekday()]}", lang)
        condition = _weather_condition(row)
        rain_mm = row.get("precip_mm")
        probability_pct = row.get("probability_pct")
        daily.append(
            {
                "weekday": weekday,
                "date": day.strftime("%d/%m"),
                "condition": condition,
                "icon": WEATHER_ICONS[condition],
                "label": translate(
                    f"forecast.{condition.replace('-', '_')}",
                    lang,
                ),
                "rain_mm": round(float(rain_mm), 1) if rain_mm is not None else None,
                "probability_pct": (
                    round(float(probability_pct))
                    if probability_pct is not None
                    else None
                ),
            }
        )

    return {
        "rows": future,
        "rain_7d": round(rain_7d, 1),
        "days_to_onset": days_to_onset,
        "source": forecast.get("source"),
        "daily": daily,
    }
