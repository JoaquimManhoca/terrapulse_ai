"""Data preparation for the climate analysis page.

Bridges the raw services (season series, trend statistics, onset detection,
model metadata) to the SVG chart builders. All functions expect an active
Flask app context.
"""

from __future__ import annotations

import pandas as pd

from ..config import Config
from ..ml.onset import detect_onsets
from ..ml.persistence import load_active_model
from ..services import climate_analysis as ca
from ..services.season_series import monthly_totals_by_month, seasonal_totals
from ..services.series_service import load_daily

MIN_REAL_PCT = 90.0
NOVEMBER_MONTH = 11


def seasonal_view() -> dict | None:
    """Section 1+2: seasonal totals with moving average and Sen trend line."""
    seasons = seasonal_totals()
    usable = [s for s in seasons if s["real_pct"] >= MIN_REAL_PCT]
    if len(usable) < 4:
        return None

    totals = [float(s["total_mm"]) for s in usable]
    years = [int(s["season"]) for s in usable]

    stats = ca.mann_kendall(totals)
    slope = ca.sens_slope(totals)
    trend_line = _trend_line_points(totals, slope) if slope else None
    moving_avg = _moving_average(totals, 5)

    bars = [
        {
            "value": totals[i],
            "label": f"{years[i] % 100:02d}",
            "title": f"{years[i]}/{(years[i] + 1) % 100:02d}: {totals[i]:.0f} mm",
            "cls": "chart-bar-fill",
        }
        for i in range(len(totals))
    ]

    return {
        "seasons": seasons,
        "n_used": len(usable),
        "excluded": len(seasons) - len(usable),
        "bars": bars,
        "moving_avg": moving_avg,
        "trend_line": trend_line,
        "mk": stats,
        "sen": slope,
        "y_max": max(totals) * 1.12,
    }


def _moving_average(values: list[float], window: int) -> list[tuple[float, float]]:
    result = []
    for i in range(len(values)):
        low = max(0, i - window + 1)
        chunk = values[low : i + 1]
        result.append((i, sum(chunk) / len(chunk)))
    return result


def _trend_line_points(values: list[float], slope: dict) -> list[tuple[float, float]]:
    """Sen regression line: intercept = median(y) - slope * median(x)."""
    gradient = float(slope["slope"])
    n = len(values)
    median_y = float(pd.Series(values).median())
    median_x = (n - 1) / 2.0
    intercept = median_y - gradient * median_x
    return [(i, intercept + gradient * i) for i in range(n)]


def november_view() -> dict | None:
    """Section 2b: November (onset month) totals and trend."""
    months = monthly_totals_by_month(NOVEMBER_MONTH)
    usable = [m for m in months if m["real_pct"] >= MIN_REAL_PCT]
    if len(usable) < 4:
        return None

    totals = [float(m["total_mm"]) for m in usable]
    years = [int(m["season"]) for m in usable]
    stats = ca.mann_kendall(totals)
    slope = ca.sens_slope(totals)

    bars = [
        {
            "value": totals[i],
            "label": f"{years[i] % 100:02d}",
            "title": f"Nov {years[i]}: {totals[i]:.0f} mm",
            "cls": "chart-bar-fill chart-bar-amber",
        }
        for i in range(len(totals))
    ]
    return {
        "bars": bars,
        "trend_line": _trend_line_points(totals, slope) if slope else None,
        "mk": stats,
        "sen": slope,
        "y_max": max(totals) * 1.12,
    }


def climatology_view() -> list[dict] | None:
    """Section 3: p10/median/p90 of monthly totals per season (Oct..Mar)."""
    rows = load_daily()
    if rows.empty:
        return None
    frame = rows.dropna(subset=["precip_mm"]).copy()
    frame["day"] = pd.to_datetime(frame["day"])
    frame = frame[frame["day"].dt.month.isin([10, 11, 12, 1, 2, 3])]
    frame["month"] = frame["day"].dt.month
    counts = frame.groupby("month")["precip_mm"].size()
    if counts.min() < 3:
        return None

    names = {10: "Out", 11: "Nov", 12: "Dez", 1: "Jan", 2: "Fev", 3: "Mar"}
    bands = []
    for month in (10, 11, 12, 1, 2, 3):
        p10 = _quantile_month(frame, month, 0.10)
        median = _quantile_month(frame, month, 0.50)
        p90 = _quantile_month(frame, month, 0.90)
        bands.append(
            {
                "tick": names[month],
                "label": f"{median:.0f}",
                "p10": p10,
                "median": median,
                "p90": p90,
                "title": f"{names[month]}: mediana {median:.0f} mm/mês (p10 {p10:.0f}, p90 {p90:.0f})",
            }
        )
    return bands


def _quantile_month(frame: pd.DataFrame, month: int, q: float) -> float:
    monthly = frame[frame["day"].dt.month == month]
    by_year = monthly.groupby(monthly["day"].dt.year)["precip_mm"].sum()
    return float(by_year.quantile(q))


def onset_calendar_view() -> dict | None:
    """Section 4: first effective onset per season + median/quartiles."""
    frame = load_daily()
    if frame.empty:
        return None
    frame = frame.dropna(subset=["precip_mm"]).copy()
    frame["day"] = pd.to_datetime(frame["day"])
    precipitation = pd.Series(
        frame["precip_mm"].to_numpy(dtype=float), index=pd.DatetimeIndex(frame["day"])
    ).sort_index()

    seasons = []
    for year in range(precipitation.index.min().year, precipitation.index.max().year + 1):
        season_start = pd.Timestamp(year, 10, 1)
        season_end = pd.Timestamp(year + 1, 3, 31)
        window = precipitation.reindex(pd.date_range(season_start, season_end))
        if window.isna().any():
            continue
        events = detect_onsets(
            window,
            season_start_month=Config.SEASON_START_MONTH,
            season_start_day=Config.SEASON_START_DAY,
            window=Config.ONSET_WINDOW_DAYS,
            threshold_mm=Config.ONSET_THRESHOLD_MM,
            dry_spell_days=Config.ONSET_DRY_SPELL_DAYS,
            horizon_days=Config.ONSET_HORIZON_DAYS,
            dry_day_mm=Config.DECISION_DRY_DAY_MM,
        )
        first = events[0] if events else None
        effective = [e for e in events if not e.false_onset]
        day_of_season = (
            (pd.Timestamp(first.onset_date) - season_start).days
            if first
            else None
        )
        seasons.append(
            {
                "season": year,
                "onset": first.onset_date.isoformat() if first else None,
                "day_of_season": day_of_season,
                "effective": bool(effective),
                "false_onsets": len(events) - len(effective),
            }
        )

    effective_days = [
        s["day_of_season"]
        for s in seasons
        if s["day_of_season"] is not None and s["effective"]
    ]
    if len(seasons) < 4:
        return None
    series = pd.Series(effective_days)
    return {
        "rows": [
            {
                "label": f"{s['season'] % 100:02d}",
                "value": s["day_of_season"],
                "title": (
                    (
                        f"{s['season']}/{(s['season'] + 1) % 100:02d}: início em {s['onset']}"
                        + ("" if s["effective"] else " (falhou)")
                    )
                    if s["onset"]
                    else f"{s['season']}/{(s['season'] + 1) % 100:02d}: sem início detectado"
                ),
                "cls": (
                    "chart-dot chart-dot-fail" if not s["effective"] else "chart-dot"
                )
                if s["day_of_season"] is not None
                else "chart-dot-none",
            }
            for s in seasons
        ],
        "median": float(series.median()) if len(effective_days) else None,
        "q1": float(series.quantile(0.25)) if len(effective_days) else None,
        "q3": float(series.quantile(0.75)) if len(effective_days) else None,
        "n_effective": len(effective_days),
        "n_seasons": len(seasons),
    }


def period_comparison_view() -> dict | None:
    """Section 5: recent vs baseline season totals with 95% CIs."""
    seasons = [s for s in seasonal_totals() if s["real_pct"] >= MIN_REAL_PCT]
    totals = [float(s["total_mm"]) for s in seasons]
    if len(totals) < 6:
        return None
    recent = totals[-10:]
    baseline = totals[:-10][-10:]
    comparison = ca.welch_ttest(recent, baseline)
    if comparison is None:
        return None
    recent_ci = ca.mean_confidence_interval(recent)
    baseline_ci = ca.mean_confidence_interval(baseline)
    if not recent_ci or not baseline_ci:
        return None
    groups = [
        {
            "label": f"{recent_ci['mean']:.0f}",
            "mean": recent_ci["mean"],
            "ci_low": recent_ci["ci_low"],
            "ci_high": recent_ci["ci_high"],
            "cls": "chart-bar-fill chart-bar-amber",
            "title": f"Últimas {len(recent)} épocas: média {recent_ci['mean']:.0f} mm (IC 95% {recent_ci['ci_low']:.0f}-{recent_ci['ci_high']:.0f})",
            "tick": "últimas 10",
        },
        {
            "label": f"{baseline_ci['mean']:.0f}",
            "mean": baseline_ci["mean"],
            "ci_low": baseline_ci["ci_low"],
            "ci_high": baseline_ci["ci_high"],
            "cls": "chart-bar-fill",
            "title": f"Épocas anteriores: média {baseline_ci['mean']:.0f} mm (IC 95% {baseline_ci['ci_low']:.0f}-{baseline_ci['ci_high']:.0f})",
            "tick": "anteriores",
        },
    ]
    return {
        "groups": groups,
        "comparison": comparison,
        "recent": recent_ci,
        "baseline": baseline_ci,
    }


def model_view() -> dict | None:
    """Section 6: feature importances and holdout metrics of the active model."""
    loaded = load_active_model(Config.MODELS_DIR)
    if loaded is None:
        return None
    model, metadata = loaded
    from ..ml.training_data import FEATURE_COLUMNS

    importances = getattr(model, "feature_importances_", None)
    items = []
    if importances is not None:
        total = float(sum(importances)) or 1.0
        ranked = sorted(
            zip(FEATURE_COLUMNS, importances), key=lambda pair: -pair[1]
        )
        items = [
            {
                "label": name,
                "pct": round(100.0 * float(value) / total, 1),
                "title": f"{name}: {100.0 * float(value) / total:.1f}%",
            }
            for name, value in ranked
        ]
    return {
        "version": metadata.get("version"),
        "saved_at": metadata.get("saved_at"),
        "data_status": metadata.get("data_status"),
        "metrics": metadata.get("metrics") or {},
        "splits": metadata.get("splits") or {},
        "importances": items,
    }
