"""Database models for TerraPulse AI."""

from __future__ import annotations

from datetime import datetime, timezone

from .extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DailyObservation(db.Model):
    __tablename__ = "daily_observations"

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Date, nullable=False, unique=True, index=True)
    precip_mm = db.Column(db.Float, nullable=True)
    coverage_pct = db.Column(db.Float, nullable=True)
    source = db.Column(db.String(32), nullable=False)
    qc_flag = db.Column(db.String(32), nullable=True)

    def to_dict(self) -> dict:
        return {
            "date": self.day.isoformat(),
            "precip_mm": self.precip_mm,
            "coverage_pct": self.coverage_pct,
            "source": self.source,
            "qc_flag": self.qc_flag,
        }


class PredictionLog(db.Model):
    __tablename__ = "prediction_log"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    state = db.Column(db.String(32), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    payload = db.Column(db.JSON, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "state": self.state,
            "confidence": self.confidence,
            "payload": self.payload,
        }
