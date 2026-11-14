"""Administrative endpoints for IMERG ingestion and model training."""

from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, current_app, jsonify, request

from ..config import Config
from ..services import harmony_ingest
from ..services.ingest import ingest_imerg
from ..services.training import train_and_persist

bp = Blueprint("admin", __name__)


@bp.post("/admin/ingest")
def ingest():
    try:
        result = ingest_imerg(
            current_app.config.get("INGEST_DIR", Config.INGEST_DIR),
            current_app.config.get("IMERG_PATTERN", Config.IMERG_PATTERN),
        )
    except FileNotFoundError as exc:
        return (
            jsonify({"error": {"code": "not_found", "message": str(exc)}}),
            404,
        )
    return jsonify(result.as_dict())


@bp.post("/admin/train")
def train():
    try:
        record = train_and_persist()
    except ValueError as exc:
        return (
            jsonify({"error": {"code": "insufficient_data", "message": str(exc)}}),
            409,
        )
    return jsonify(record)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@bp.post("/admin/ingest-harmony")
def ingest_harmony():
    """Start a background IMERG Final ingestion via NASA Harmony.

    Body (JSON, optional): {"start_date": "2000-06-01", "end_date": "2026-07-17"}.
    IMERG Final needs ~120 days of lag; end defaults to today - 120 days.
    """
    body = request.get_json(silent=True) or {}
    start = _parse_date(body.get("start_date"))
    end = _parse_date(body.get("end_date"))
    try:
        status = harmony_ingest.start_harmony_ingest(start, end)
    except ValueError as exc:
        return (
            jsonify({"error": {"code": "invalid_range", "message": str(exc)}}),
            400,
        )
    except RuntimeError as exc:
        return (
            jsonify({"error": {"code": "already_running", "message": str(exc)}}),
            409,
        )
    return jsonify(status), 202


@bp.get("/admin/ingest-harmony/status")
def ingest_harmony_status():
    return jsonify(harmony_ingest.harmony_ingest_status())
