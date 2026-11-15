"""Administrative endpoints for IMERG ingestion and model training."""

from __future__ import annotations

import hmac
from datetime import date, timedelta

from flask import Blueprint, current_app, jsonify, request

from ..config import Config
from ..services import harmony_ingest
from ..services.ingest import ingest_imerg
from ..services.training import train_and_persist

bp = Blueprint("admin", __name__)


def _denied(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


@bp.before_request
def _require_admin_token():
    """Every admin route needs a shared secret sent as X-Admin-Token."""
    expected = current_app.config.get("ADMIN_TOKEN")
    if not expected:
        return _denied(
            "admin_disabled",
            "ADMIN_TOKEN is not configured; the admin API is disabled.",
            503,
        )
    provided = request.headers.get("X-Admin-Token")
    if not provided or not hmac.compare_digest(str(provided), str(expected)):
        return _denied(
            "unauthorized",
            "A valid X-Admin-Token header is required.",
            401,
        )
    return None


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
