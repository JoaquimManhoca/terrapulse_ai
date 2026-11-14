"""Decision endpoint."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from ..services.decision import build_decision

bp = Blueprint("decision", __name__)


@bp.get("/decision")
def decision():
    return jsonify(build_decision(lang=g.get("lang", "pt")))
