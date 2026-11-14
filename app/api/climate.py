"""Climate trend endpoints (Mann-Kendall, Sen's slope, t-test, CIs)."""

from __future__ import annotations

from flask import Blueprint, jsonify

from ..services import climate_analysis as ca
from ..services.season_series import monthly_totals_by_month, seasonal_totals
from ..services.series_service import data_status

bp = Blueprint("climate", __name__)

MIN_REAL_PCT = 90.0


@bp.get("/climate/trends")
def climate_trends():
    """Rainy-season trend analysis over the full stored archive.

    - ``trend_seasonal``: Mann-Kendall + Sen's slope on the Oct-Mar totals.
    - ``trend_november``: same, restricted to the onset month (November).
    - ``period_comparison``: Welch t-test, recent 10 seasons vs the 10
      before them, each mean with a 95% confidence interval.
    - Only seasons with at least ``MIN_REAL_PCT`` real observations feed the
      statistics; partial or synthetic seasons stay visible in ``seasons``
      but are excluded from the trends.
    """
    seasons = seasonal_totals()
    usable = [item for item in seasons if item["real_pct"] >= MIN_REAL_PCT]
    excluded = len(seasons) - len(usable)

    totals = [item["total_mm"] for item in usable]
    november = [
        item["total_mm"]
        for item in monthly_totals_by_month(11)
        if item["real_pct"] >= MIN_REAL_PCT
    ]

    trend_seasonal = ca.mann_kendall(totals)
    slope_seasonal = ca.sens_slope(totals)
    trend_november = ca.mann_kendall(november)
    slope_november = ca.sens_slope(november)

    recent = totals[-10:]
    baseline = totals[:-10][-10:]
    comparison = ca.welch_ttest(recent, baseline)

    if trend_seasonal is None and trend_november is None:
        return (
            jsonify(
                {
                    "error": {
                        "code": "insufficient_data",
                        "message": "Fewer than 4 rainy seasons available.",
                    }
                }
            ),
            409,
        )

    return jsonify(
        {
            "data_status": data_status(),
            "confidence_level": 0.95,
            "n_seasons": len(seasons),
            "seasons_used": len(usable),
            "seasons_excluded": excluded,
            "min_real_pct": MIN_REAL_PCT,
            "seasons": seasons,
            "trend_seasonal": trend_seasonal,
            "slope_seasonal": slope_seasonal,
            "trend_november": trend_november,
            "slope_november": slope_november,
            "recent_mean": ca.mean_confidence_interval(recent),
            "baseline_mean": ca.mean_confidence_interval(baseline),
            "period_comparison": comparison,
        }
    )
