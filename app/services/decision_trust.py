"""Data provenance and confidence summary for the decision UI."""

from __future__ import annotations

import pandas as pd

from ..i18n import translate


def _source_label(source: str) -> str:
    lowered = source.lower()
    if "final" in lowered:
        return "IMERG Final"
    if "early" in lowered:
        return "IMERG Early"
    if "synthetic" in lowered:
        return "Synthetic"
    return source


def _trust_summary(
    frame: pd.DataFrame,
    series: pd.Series,
    forecast_info: dict | None,
    data_age_days: int,
    data_stale: bool,
    confidence: float,
    model_version: str,
    state: str,
    lang: str,
) -> dict:
    sources = []
    if "source" in frame:
        sources = sorted(
            {
                _source_label(str(source))
                for source in frame["source"].dropna().unique()
            }
        )
    coverage_pct = None
    if "coverage_pct" in frame:
        coverage = pd.to_numeric(frame["coverage_pct"], errors="coerce").tail(30)
        if coverage.notna().any():
            coverage_pct = round(float(coverage.mean()), 1)
    level = "high" if confidence >= 0.75 else "medium" if confidence >= 0.55 else "low"
    change_key = "trust.change_stale" if data_stale else f"trust.change_{state.lower()}"
    forecast_source = (forecast_info or {}).get("source")
    if forecast_source == "open-meteo":
        forecast_source = "Open-Meteo"
    return {
        "sources_label": " + ".join(sources) if sources else None,
        "coverage_pct": coverage_pct,
        "observation_days": len(frame),
        "history_years": int(series.index.year.nunique()),
        "forecast_days": len((forecast_info or {}).get("rows", [])),
        "forecast_source": forecast_source,
        "model_version": model_version,
        "data_age_days": data_age_days,
        "level": level,
        "change": translate(change_key, lang),
        "stale": data_stale,
    }
