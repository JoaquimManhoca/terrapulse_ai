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


class DecisionFeedback(db.Model):
    __tablename__ = "decision_feedback"
    __table_args__ = (
        db.Index(
            "uq_decision_feedback_submission_id",
            "submission_id",
            unique=True,
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    decision_date = db.Column(db.Date, nullable=False, index=True)
    choice = db.Column(db.String(24), nullable=False, index=True)
    state = db.Column(db.String(32), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    model_version = db.Column(db.String(64), nullable=True)
    last_observation = db.Column(db.Date, nullable=True)
    region = db.Column(db.String(32), nullable=False)
    crop = db.Column(db.String(32), nullable=False)
    lang = db.Column(db.String(16), nullable=False)
    planting_date = db.Column(db.Date, nullable=True)
    field_outcome = db.Column(db.String(40), nullable=True)
    outcome_reported_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "decision_date": self.decision_date.isoformat(),
            "choice": self.choice,
            "state": self.state,
            "confidence": self.confidence,
            "model_version": self.model_version,
            "last_observation": (
                self.last_observation.isoformat()
                if self.last_observation
                else None
            ),
            "region": self.region,
            "crop": self.crop,
            "lang": self.lang,
            "planting_date": (
                self.planting_date.isoformat() if self.planting_date else None
            ),
            "field_outcome": self.field_outcome,
            "outcome_reported_at": (
                self.outcome_reported_at.isoformat()
                if self.outcome_reported_at
                else None
            ),
        }
