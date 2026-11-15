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
from .decision_forecast import _forecast_summary
from .decision_plan import _plan_summary
from .decision_trust import _trust_summary
from .decision_weather import (
    REASON_ICONS,
    STATE_ICONS,
    WEATHER_ICONS,
    _recommendation_weather,
    _weather_condition,
)
from .forecast import fetch_open_meteo
from .series_service import calendar_series, data_status, load_daily


def _local_today() -> date:
    return date.today()


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
        "plan": None,
        "trust": None,
        "last_updated": None,
        "last_day": None,
        "data_age_days": None,
        "data_stale": True,
        "reference_date": _local_today().isoformat(),
        "season": None,
        "data_status": "empty",
        "model_version": "heuristic-v0",
        "lang": lang,
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

    series = calendar_series()
    last_day = series.index.max().date()
    today = _local_today()
    data_age_days = max(0, (today - last_day).days)
    data_stale = data_age_days > Config.DATA_MAX_AGE_DAYS

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

    forecast = (
        fetch_open_meteo() if forecast_enabled and not data_stale else None
    )
    forecast_info = _forecast_summary(forecast, today, lang)

    onset_prob, model_version_used = _model_onset_probability(frame)
    model_version = model_version_used or "heuristic-v0"

    state, confidence, days_to_plant = _decide(
        month=today.month,
        rain_7=rain_7,
        dry_streak=dry_streak,
        current_onset=current_onset,
        false_rate=false_rate,
        forecast_info=forecast_info,
        onset_prob=onset_prob,
    )
    if data_stale:
        state = "WAIT"
        confidence = round(min(confidence, 0.5), 2)
        days_to_plant = None
    recommendation = translate(
        "decision.action_stale" if data_stale else f"decision.action_{state.lower()}",
        lang,
    )
    weather = (
        dict(forecast_info["daily"][0])
        if forecast_info and forecast_info["daily"]
        else _recommendation_weather(state, lang)
    )
    if forecast_info and forecast_info["daily"]:
        weather["caption"] = f"{weather['weekday']}, {weather['date']}"

    reasons = []
    if data_stale:
        reasons.append(
            _reason(
                "data_stale",
                translate("reason.data_stale", lang),
                data_age_days,
                translate("common.days", lang),
            )
        )
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
    elif forecast_enabled and not data_stale:
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

    plan = _plan_summary(
        series,
        forecast_info,
        today,
        state,
        days_to_plant,
        data_stale,
        lang,
    )
    trust = _trust_summary(
        frame,
        series,
        forecast_info,
        data_age_days,
        data_stale,
        confidence,
        model_version,
        state,
        lang,
    )

    if today.month >= Config.SEASON_START_MONTH:
        season = f"{today.year}/{today.year + 1}"
    else:
        season = f"{today.year - 1}/{today.year}"

    headline = translate("state.stale" if data_stale else f"state.{state.lower()}", lang)
    summary = translate(
        "state.stale.sub" if data_stale else f"state.{state.lower()}.sub",
        lang,
    )
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
        "plan": plan,
        "trust": trust,
        "last_updated": last_day.strftime("%d/%m/%Y"),
        "last_day": last_day.isoformat(),
        "data_age_days": data_age_days,
        "data_stale": data_stale,
        "reference_date": today.isoformat(),
        "season": season,
        "data_status": data_status(),
        "model_version": model_version,
        "lang": lang,
    }
