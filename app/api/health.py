"""Health and status endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify
from sqlalchemy import func

from ..extensions import db
from ..models import DailyObservation
from ..services.series_service import data_status

bp = Blueprint("health", __name__)

SYNTHETIC_SOURCE = "synthetic"


@bp.get("/health")
def health():
    counts = dict(
        db.session.query(DailyObservation.source, func.count())
        .group_by(DailyObservation.source)
        .all()
    )
    latest = db.session.query(func.max(DailyObservation.day)).scalar()
    return jsonify(
        {
            "status": "ok",
            "service": "TerraPulse AI",
            "phase": "1",
            "observations": sum(counts.values()),
            "real_observations": sum(
                count
                for source, count in counts.items()
                if source != SYNTHETIC_SOURCE
            ),
            "synthetic_observations": counts.get(SYNTHETIC_SOURCE, 0),
            "sources": counts,
            "latest_observation": latest.isoformat() if latest else None,
            "data_status": data_status(),
        }
    )
