"""Weather, icon and state helpers for the decision engine."""

from __future__ import annotations

from ..i18n import translate

STATE_ICONS = {
    "PLANT_NOW": "sprout",
    "WAIT": "clock",
    "PLANT_IN_DAYS": "rain",
    "HIGH_RISK": "alert",
}

WEATHER_ICONS = {
    "sunny": "sun",
    "partly-cloudy": "partly_cloudy",
    "cloudy": "cloudy",
    "rainy": "rain",
    "unknown": "cloudy",
}

STATE_WEATHER = {
    "PLANT_NOW": "sunny",
    "WAIT": "cloudy",
    "PLANT_IN_DAYS": "partly-cloudy",
    "HIGH_RISK": "partly-cloudy",
}

REASON_ICONS = {
    "rain_7d": "rain",
    "dry_streak": "sun",
    "historical_false": "history",
    "forecast_rain": "rain",
    "forecast_unavailable": "alert",
    "onset_seen": "calendar",
    "onset_none": "sun",
    "ml_onset_prob": "spark",
    "data_stale": "alert",
}

_RAIN_CHANCE_THRESHOLD_PCT = 50.0
_RAINY_WEATHER_CODES = frozenset(
    (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99)
)


def _weather_condition(row: dict) -> str:
    code = row.get("weather_code")
    probability_pct = row.get("probability_pct")
    is_rain_code = code in _RAINY_WEATHER_CODES
    has_precipitation = (row.get("precip_mm") or 0) > 0

    if probability_pct is not None:
        if probability_pct >= _RAIN_CHANCE_THRESHOLD_PCT:
            return "rainy"
        if is_rain_code or has_precipitation:
            return "cloudy"

    if code in (0, 1):
        return "sunny"
    if code == 2:
        return "partly-cloudy"
    if code in (3, 45, 48):
        return "cloudy"
    if is_rain_code:
        return "rainy"
    if code is None and has_precipitation:
        return "rainy"
    return "unknown"


def _recommendation_weather(state: str, lang: str) -> dict:
    condition = STATE_WEATHER[state]
    return {
        "condition": condition,
        "icon": WEATHER_ICONS[condition],
        "label": translate(f"forecast.{condition.replace('-', '_')}", lang),
        "caption": translate("forecast.recommendation_visual", lang),
        "probability_pct": None,
    }


def _climate_condition(probability_pct: float | None) -> str:
    if probability_pct is None:
        return "unknown"
    if probability_pct >= 50:
        return "rainy"
    if probability_pct >= 25:
        return "partly-cloudy"
    return "sunny"
