"""History and climatology endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..services.series_service import (
    daily_series,
    data_status,
    load_daily,
    monthly_totals,
    yearly_totals,
)

bp = Blueprint("series", __name__)


@bp.get("/history")
def history():
    limit = min(max(int(request.args.get("days", 90)), 1), 3650)
    series = daily_series()
    tail = series.tail(limit)
    return jsonify(
        {
            "data_status": data_status(),
            "days": len(tail),
            "series": [
                {
                    "date": ts.date().isoformat(),
                    "precip_mm": None if value != value else round(float(value), 1),
                }
                for ts, value in tail.items()
            ],
        }
    )


@bp.get("/climatology")
def climatology():
    return jsonify(
        {
            "data_status": data_status(),
            "monthly": monthly_totals(24),
            "yearly": yearly_totals(),
            "rows": len(load_daily()),
        }
    )
