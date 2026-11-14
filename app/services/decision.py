"""Decision engine (Phase 2).

This module turns the cleaned rainfall series into a single, plain-language
planting recommendation. When a trained model is persisted under
``data/models`` it informs the onset probability and the decision state;
otherwise the Phase 0 heuristic keeps the same output contract.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from flask import current_app

from ..config import Config
from ..i18n import translate
from ..ml.onset import OnsetEvent, detect_onsets, latest_wet_event
from ..ml.persistence import load_active_model
from ..ml.training_data import build_inference_frame
from .forecast import fetch_open_meteo
from .series_service import daily_series, data_status, load_daily

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
}

_RAIN_CHANCE_THRESHOLD_PCT = 50.0
_RAINY_WEATHER_CODES = frozenset(
    (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99)
)


def _local_today() -> date:
    return date.today()


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


def _model_onset_probability(
    frame: pd.DataFrame,
) -> tuple[float | None, str | None]:
    """P(effective onset within 21 days) from the persisted model, if any."""
    bundle = load_active_model(current_app.config["MODELS_DIR"])
    if bundle is None:
        return None, None
    model, metadata = bundle
    if metadata.get("data_status") != "real":
        return None, None
    inference = build_inference_frame(frame)
    if inference is None or inference.isna().to_numpy().any():
        return None, None
    probability = model.predict_proba(inference)[0, 1]
    return float(probability), metadata.get("version")


def _season_day(day: date, start_month: int = Config.SEASON_START_MONTH) -> int:
    """Days elapsed since the start of the rainy season (1 October by default)."""
    year = day.year if day.month >= start_month else day.year - 1
    return (day - date(year, start_month, 1)).days


def _season_label(offset: float | None, start_month: int = Config.SEASON_START_MONTH) -> str | None:
    if offset is None:
        return None
    reference = date(2001, start_month, 1) + timedelta(days=int(round(offset)))
    return reference.strftime("%d/%m")


def _dry_streak(series, dry_mm: float) -> int:
    streak = 0
    for value in series.to_numpy(dtype=float)[::-1]:
        if np.isnan(value):
            break
        if value < dry_mm:
            streak += 1
        else:
            break
    return streak


def _reason(code: str, label: str, value: Any = None, unit: str | None = None) -> dict:
    return {
        "code": code,
        "label": label,
        "value": value,
        "unit": unit,
        "icon": REASON_ICONS.get(code, "info"),
    }


def _empty_decision(lang: str) -> dict:
    recommendation = translate("decision.no_data", lang)
    return {
        "state": "WAIT",
        "confidence": 0.0,
        "days_to_plant": None,
        "icon": "alert",
        "headline": translate("state.wait", lang),
        "recommendation": recommendation,
        "summary": translate("decision.no_data", lang),
        "weather": _recommendation_weather("WAIT", lang),
        "speech": translate("decision.no_data", lang),
        "reasons": [],
        "probabilities": {},
        "climatology": {},
        "forecast": None,
        "last_updated": None,
        "last_day": None,
        "season": None,
        "data_status": "empty",
        "model_version": "heuristic-v0",
        "lang": lang,
    }


def _forecast_summary(
    forecast: dict | None,
    last_day: date,
    lang: str = "pt",
) -> dict | None:
    if not forecast:
        return None
    future = [
        row
        for row in forecast.get("rows", [])
        if (row.get("date") or "") > last_day.isoformat()
    ]
    future = future[:14]
    rain_7d = sum((row.get("precip_mm") or 0.0) for row in future[:7])
    values = [row.get("precip_mm") or 0.0 for row in future]
    days_to_onset = None
    last_start = len(values) - Config.ONSET_WINDOW_DAYS
    for index in range(max(0, last_start + 1)):
        if sum(values[index:index + Config.ONSET_WINDOW_DAYS]) >= Config.ONSET_THRESHOLD_MM:
            days_to_onset = index
            break

    daily = []
    today = _local_today().isoformat()
    current_rows = sorted(
        (
            row
            for row in forecast.get("rows", [])
            if row.get("date") and row["date"] >= today
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


def _decide(
    month: int,
    rain_7: float,
    dry_streak: int,
    current_onset: OnsetEvent | None,
    false_rate: float | None,
    forecast_info: dict | None,
    onset_prob: float | None = None,
) -> tuple[str, float, int | None]:
    if current_onset is not None and (current_onset.false_onset or dry_streak >= 5):
        confidence = 0.72 + min(0.2, (false_rate or 0.3) * 0.2)
        return "HIGH_RISK", round(min(confidence, 0.95), 2), None

    if rain_7 >= 20 and dry_streak <= 2:
        confidence = min(0.9, 0.6 + rain_7 / 80)
        return "PLANT_NOW", round(confidence, 2), 0

    if (
        onset_prob is not None
        and onset_prob >= 0.75
        and current_onset is None
    ):
        return "PLANT_IN_DAYS", round(max(0.6, min(0.9, onset_prob)), 2), None

    if forecast_info and forecast_info.get("days_to_onset") is not None:
        days = int(forecast_info["days_to_onset"])
        if days <= 7:
            return "PLANT_IN_DAYS", 0.65, max(0, days)

    if forecast_info and forecast_info.get("rain_7d", 0.0) >= 15:
        return "PLANT_IN_DAYS", 0.6, 3

    if month in (4, 5, 6, 7, 8, 9):
        return "WAIT", 0.8, None

    return "WAIT", 0.55, None


def build_decision(lang: str = "pt", forecast_enabled: bool | None = None) -> dict:
    if forecast_enabled is None:
        forecast_enabled = current_app.config["FORECAST_ENABLED"]

    frame = load_daily()
    if frame.empty:
        return _empty_decision(lang)

    series = daily_series()
    last_day = series.index.max().date()

    rain_7 = float(np.nansum(series.tail(7).to_numpy(dtype=float)))
    dry_streak = _dry_streak(series, Config.DECISION_DRY_DAY_MM)

    onsets = detect_onsets(
        series,
        season_start_month=Config.SEASON_START_MONTH,
        season_start_day=Config.SEASON_START_DAY,
        window=Config.ONSET_WINDOW_DAYS,
        threshold_mm=Config.ONSET_THRESHOLD_MM,
        dry_spell_days=Config.ONSET_DRY_SPELL_DAYS,
        horizon_days=Config.ONSET_HORIZON_DAYS,
        dry_day_mm=Config.DECISION_DRY_DAY_MM,
    )

    complete_onsets = [
        onset
        for onset in onsets
        if onset.onset_date + timedelta(days=Config.ONSET_HORIZON_DAYS) <= last_day
    ]
    climatology_onsets = complete_onsets or onsets

    false_rate = None
    onset_offsets: list[int] = []
    median_offset = None
    if climatology_onsets:
        false_rate = sum(1 for onset in climatology_onsets if onset.false_onset) / len(climatology_onsets)
        onset_offsets = [_season_day(onset.onset_date) for onset in climatology_onsets]
        median_offset = float(np.median(onset_offsets))

    current_onset = latest_wet_event(
        series,
        lookback_days=30,
        window=Config.ONSET_WINDOW_DAYS,
        threshold_mm=Config.ONSET_THRESHOLD_MM,
        dry_spell_days=Config.ONSET_DRY_SPELL_DAYS,
        horizon_days=14,
        dry_day_mm=Config.DECISION_DRY_DAY_MM,
    )

    forecast = fetch_open_meteo() if forecast_enabled else None
    forecast_info = _forecast_summary(forecast, last_day, lang)

    onset_prob, model_version_used = _model_onset_probability(frame)

    state, confidence, days_to_plant = _decide(
        month=last_day.month,
        rain_7=rain_7,
        dry_streak=dry_streak,
        current_onset=current_onset,
        false_rate=false_rate,
        forecast_info=forecast_info,
        onset_prob=onset_prob,
    )
    recommendation = translate(f"decision.action_{state.lower()}", lang)
    weather = (
        dict(forecast_info["daily"][0])
        if forecast_info and forecast_info["daily"]
        else _recommendation_weather(state, lang)
    )
    if forecast_info and forecast_info["daily"]:
        weather["caption"] = f"{weather['weekday']}, {weather['date']}"

    reasons = []
    if current_onset is not None:
        reasons.append(
            _reason(
                "onset_seen",
                translate("reason.onset_seen", lang),
                current_onset.onset_date.strftime("%d/%m/%Y"),
            )
        )
    else:
        reasons.append(_reason("onset_none", translate("reason.onset_none", lang)))
    reasons.append(
        _reason(
            "rain_7d",
            translate("reason.rain_7d", lang),
            round(rain_7, 1),
            translate("common.mm", lang),
        )
    )
    reasons.append(
        _reason(
            "dry_streak",
            translate("reason.dry_streak", lang),
            dry_streak,
            translate("common.days", lang),
        )
    )
    if false_rate is not None:
        reasons.append(
            _reason(
                "historical_false",
                translate("reason.historical_false", lang),
                f"{round(false_rate * 100)}%",
            )
        )
    if onset_prob is not None:
        reasons.append(
            _reason(
                "ml_onset_prob",
                translate("reason.ml_onset_prob", lang),
                f"{round(onset_prob * 100)}%",
            )
        )
    if forecast_info is not None:
        reasons.append(
            _reason(
                "forecast_rain",
                translate("reason.forecast_rain", lang),
                forecast_info["rain_7d"],
                translate("common.mm", lang),
            )
        )
    elif forecast_enabled:
        reasons.append(
            _reason("forecast_unavailable", translate("reason.forecast_unavailable", lang))
        )

    onset_7d = 0.25
    if current_onset is not None and not current_onset.false_onset:
        onset_7d = 0.9
    elif forecast_info and forecast_info.get("days_to_onset") is not None and forecast_info["days_to_onset"] <= 7:
        onset_7d = 0.75
    elif rain_7 >= 15:
        onset_7d = 0.6

    if current_onset is not None:
        false_probability = 0.9 if current_onset.false_onset else max(0.05, (false_rate or 0.3) * 0.5)
    else:
        false_probability = false_rate if false_rate is not None else 0.5

    climatology = {
        "years": len(climatology_onsets),
        "false_onset_rate": round(false_rate, 3) if false_rate is not None else None,
        "median_onset": _season_label(median_offset),
        "earliest_onset": _season_label(min(onset_offsets)) if onset_offsets else None,
        "latest_onset": _season_label(max(onset_offsets)) if onset_offsets else None,
    }

    if last_day.month >= Config.SEASON_START_MONTH:
        season = f"{last_day.year}/{last_day.year + 1}"
    else:
        season = f"{last_day.year - 1}/{last_day.year}"

    headline = translate(f"state.{state.lower()}", lang)
    summary = translate(f"state.{state.lower()}.sub", lang)
    speech_parts = [
        f"{reason['label']} {reason['value']}{(' ' + reason['unit']) if reason['unit'] else ''}".strip()
        for reason in reasons[:3]
    ]
    speech = (
        f"{headline}. {recommendation} {summary} "
        f"{translate('decision.reasons', lang)}: "
        + "; ".join(speech_parts)
    )

    return {
        "state": state,
        "confidence": confidence,
        "days_to_plant": days_to_plant,
        "icon": STATE_ICONS[state],
        "headline": headline,
        "recommendation": recommendation,
        "summary": summary,
        "weather": weather,
        "speech": speech,
        "reasons": reasons,
        "probabilities": {
            "onset_7d": round(onset_7d, 2),
            "onset_21d": (
                round(onset_prob, 2) if onset_prob is not None else None
            ),
            "false_onset": round(false_probability, 2),
        },
        "climatology": climatology,
        "forecast": forecast_info,
        "last_updated": last_day.strftime("%d/%m/%Y"),
        "last_day": last_day.isoformat(),
        "season": season,
        "data_status": data_status(),
        "model_version": model_version_used or "heuristic-v0",
        "lang": lang,
    }
