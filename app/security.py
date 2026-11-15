"""Lightweight request guards: admin token, CSRF and feedback throttling."""

from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque

from flask import current_app, request, session

_CSRF_SESSION_KEY = "csrf_token"
_hits: dict[str, deque[float]] = defaultdict(deque)


def issue_csrf_token() -> str:
    """Return the session CSRF token, creating it on first use."""
    token = session.get(_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_SESSION_KEY] = token
    return token


def _presented_csrf_token() -> str | None:
    token = None
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        token = payload.get("csrf_token")
    else:
        token = request.form.get("csrf_token")
    return token or request.headers.get("X-CSRF-Token")


def csrf_is_valid() -> bool:
    """Validate a same-origin token sent as a form field or header."""
    expected = session.get(_CSRF_SESSION_KEY)
    provided = _presented_csrf_token()
    if not expected or not provided:
        return False
    return hmac.compare_digest(str(expected), str(provided))


def rate_limit_exceeded(key: str, limit: int, window: float) -> bool:
    """Sliding-window limiter. Records the hit and reports if it overflows."""
    now = time.monotonic()
    bucket = _hits[key]
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def feedback_rate_limited() -> bool:
    limit = int(current_app.config.get("FEEDBACK_RATE_LIMIT", 30))
    window = float(current_app.config.get("FEEDBACK_RATE_WINDOW", 60))
    key = f"feedback:{request.remote_addr or 'unknown'}"
    return rate_limit_exceeded(key, limit, window)


def reset_rate_limits() -> None:
    """Clear limiter state (used by tests)."""
    _hits.clear()
