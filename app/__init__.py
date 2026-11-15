"""TerraPulse AI application package."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import (
    Flask,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .config import Config, _engine_options
from .extensions import cors, db
from .i18n import LANGUAGES, SUPPORTED_LANGUAGES, get_catalog, translate

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data:",
        "connect-src 'self'",
        "manifest-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)


FEEDBACK_CHOICES = frozenset({"planted", "waited", "not_helpful"})
DECISION_STATES = frozenset(
    {"PLANT_NOW", "WAIT", "PLANT_IN_DAYS", "HIGH_RISK"}
)


def _iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _safe_referrer() -> str | None:
    """Only redirect back to this origin, never to an external referrer."""
    referrer = request.referrer
    if not referrer:
        return None
    parts = urlsplit(referrer)
    if parts.scheme not in {"http", "https"}:
        return None
    if (parts.netloc or "").lower() != request.host.lower():
        return None
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "lang"
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = _engine_options(
        app.config["SQLALCHEMY_DATABASE_URI"], app.config["IS_VERCEL"]
    )

    if app.config["IS_VERCEL"]:
        if not app.config["SQLALCHEMY_DATABASE_URI"].startswith(
            "postgresql+psycopg://"
        ):
            raise RuntimeError(
                "Vercel deployment requires DATABASE_URL to point to PostgreSQL."
            )
        secret_key = app.config["SECRET_KEY"]
        if (
            secret_key == "dev-secret-change-me"
            or not secret_key
            or len(secret_key) < 32
        ):
            raise RuntimeError(
                "Vercel deployment requires a SECRET_KEY with at least 32 characters."
            )
    else:
        for path in (
            app.config["RAW_DIR"],
            app.config["INTERIM_DIR"],
            app.config["PROCESSED_DIR"],
            app.config["MODELS_DIR"],
        ):
            path.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})

    if app.config["IS_VERCEL"]:
        from .services.training import active_model_info

        with app.app_context():
            model_info = active_model_info()
        if model_info:
            app.logger.info(
                "Bundled onset model active: %s", model_info.get("version")
            )
        else:
            app.logger.warning(
                "No onset model bundled; the decision uses the heuristic."
            )

    from .api import climate, decision as decision_api, health, series

    from .cli import register_cli

    if not app.config["IS_VERCEL"]:
        from .api import admin

        app.register_blueprint(admin.bp, url_prefix="/api")

    app.register_blueprint(health.bp, url_prefix="/api")
    app.register_blueprint(decision_api.bp, url_prefix="/api")
    app.register_blueprint(series.bp, url_prefix="/api")
    app.register_blueprint(climate.bp, url_prefix="/api")
    register_cli(app)

    @app.before_request
    def _set_language() -> None:
        if request.path.startswith("/static/") or request.path == (
            "/service-worker.js"
        ):
            return
        requested = request.args.get("lang")
        lang = requested or session.get("lang") or app.config["DEFAULT_LANGUAGE"]
        if lang not in SUPPORTED_LANGUAGES:
            lang = app.config["DEFAULT_LANGUAGE"]
        g.lang = lang
        if requested and session.get("lang") != lang:
            session["lang"] = lang

    @app.context_processor
    def _inject_globals() -> dict:
        lang = g.get("lang", app.config["DEFAULT_LANGUAGE"])
        return {
            "t": lambda key: translate(key, lang),
            "lang": lang,
            "languages": LANGUAGES,
            "catalog": get_catalog(lang),
            "app_version": "0.2.0",
        }

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault(
            "Content-Security-Policy", CONTENT_SECURITY_POLICY
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=()",
        )
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = (
                "public, max-age=86400, stale-while-revalidate=604800"
            )
        elif request.path == "/service-worker.js":
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.route("/language/<lang_code>")
    def set_language(lang_code: str):
        if lang_code in SUPPORTED_LANGUAGES:
            session["lang"] = lang_code
        return redirect(_safe_referrer() or url_for("index"))

    @app.route("/service-worker.js")
    def service_worker():
        response = send_from_directory(
            app.static_folder,
            "service-worker.js",
            mimetype="application/javascript",
        )
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    def _probability_rows(decision) -> list[dict]:
        probabilities = decision.get("probabilities") or {}
        onset_21 = probabilities.get("onset_21d")
        onset_7 = probabilities.get("onset_7d")
        false_onset = probabilities.get("false_onset")

        def row(key, value, cls, is_ml):
            if value is None:
                return None
            pct = int(round(100.0 * float(value)))
            return {
                "key": key,
                "pct": pct,
                "cls": cls,
                "is_ml": is_ml,
            }

        return [
            item
            for item in (
                row("why.prob_onset_21", onset_21, "prob-bar-primary", True),
                row("why.prob_onset_7", onset_7, "prob-bar-secondary", False),
                row("why.prob_false", false_onset, "prob-bar-warn", False),
            )
            if item is not None
        ]

    def _selection() -> tuple[str, str]:
        regions = current_app.config["REGIONS"]
        crops = current_app.config["CROPS"]
        region = request.args.get("region") or session.get("region") or current_app.config["DEFAULT_REGION"]
        crop = request.args.get("crop") or session.get("crop") or current_app.config["DEFAULT_CROP"]
        if region not in regions:
            region = current_app.config["DEFAULT_REGION"]
        if crop not in crops:
            crop = current_app.config["DEFAULT_CROP"]
        session["region"] = region
        session["crop"] = crop
        return region, crop

    @app.route("/")
    def index():
        from .services.decision import build_decision

        region, crop = _selection()
        regions = current_app.config["REGIONS"]
        crops = current_app.config["CROPS"]
        supported = regions[region]["supported"] and crops[crop]["supported"]
        return render_template(
            "decision.html",
            decision=build_decision(lang=g.lang) if supported else None,
            feedback_submission_id=str(uuid4()),
            regions=regions,
            crops=crops,
            selected_region=region,
            selected_crop=crop,
            selection_supported=supported,
        )

    @app.post("/feedback")
    def feedback():
        from .models import DecisionFeedback

        payload = request.get_json(silent=True) if request.is_json else request.form
        payload = payload or {}
        wants_json = (
            request.is_json
            or request.accept_mimetypes.best == "application/json"
        )
        choice = str(payload.get("choice", "")).strip()
        state = str(payload.get("state", "")).strip().upper()
        try:
            submission_id = str(UUID(str(payload.get("submission_id", ""))))
        except (AttributeError, TypeError, ValueError):
            submission_id = None

        if (
            choice not in FEEDBACK_CHOICES
            or state not in DECISION_STATES
            or submission_id is None
        ):
            if wants_json:
                return jsonify(
                    {"error": {"code": "invalid_feedback"}}
                ), 400
            return redirect(url_for("index"))

        def feedback_response(record, status_code=201):
            if wants_json:
                return jsonify(
                    {"status": "ok", "feedback": record.to_dict()}
                ), status_code
            return redirect(url_for("index", feedback=1))

        try:
            confidence = float(payload.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))

        region, crop = _selection()
        record = DecisionFeedback(
            submission_id=submission_id,
            decision_date=(
                _iso_date(payload.get("reference_date")) or date.today()
            ),
            choice=choice,
            state=state,
            confidence=confidence,
            model_version=(
                str(payload.get("model_version", "")).strip()[:64] or None
            ),
            last_observation=_iso_date(payload.get("last_day")),
            region=region,
            crop=crop,
            lang=g.lang,
        )
        try:
            db.session.add(record)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            try:
                duplicate = DecisionFeedback.query.filter_by(
                    submission_id=submission_id
                ).one_or_none()
            except SQLAlchemyError:
                current_app.logger.exception(
                    "Unable to resolve a repeated feedback submission."
                )
                if wants_json:
                    return jsonify(
                        {"error": {"code": "feedback_unavailable"}}
                    ), 503
                return redirect(url_for("index"))
            if duplicate is not None:
                return feedback_response(duplicate, status_code=200)
            current_app.logger.exception("Unable to save decision feedback.")
            if wants_json:
                return jsonify(
                    {"error": {"code": "feedback_unavailable"}}
                ), 503
            return redirect(url_for("index"))
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Unable to save decision feedback.")
            if wants_json:
                return jsonify(
                    {"error": {"code": "feedback_unavailable"}}
                ), 503
            return redirect(url_for("index"))

        return feedback_response(record)

    @app.route("/porque")
    def why():
        from .services.decision import build_decision
        from .services.series_service import recent_days

        decision = build_decision(lang=g.lang)
        return render_template(
            "why.html",
            decision=decision,
            recent=recent_days(30),
            probabilities=_probability_rows(decision),
        )

    @app.route("/historico")
    def history():
        from .services.series_service import (
            data_status,
            last_updated,
            monthly_totals,
            season_monthly_totals,
        )

        return render_template(
            "history.html",
            monthly=monthly_totals(24),
            seasons=season_monthly_totals(lang=g.lang),
            data_status=data_status(),
            last_updated=last_updated(),
        )

    @app.route("/analise")
    def analysis():
        from .services import charts
        from .services.climate_viz import (
            climatology_view,
            model_view,
            november_view,
            onset_calendar_view,
            period_comparison_view,
            seasonal_view,
        )

        lang = g.lang
        sections = {
            "seasonal": seasonal_view(lang),
            "november": november_view(lang),
            "climatology": climatology_view(lang),
            "onset": onset_calendar_view(lang),
            "comparison": period_comparison_view(lang),
            "model": model_view(lang),
        }
        charts_out = {
            "seasonal": charts.bar_chart(
                sections["seasonal"]["bars"],
                line=sections["seasonal"]["trend_line"],
                line_label=translate("chart.sen_trend", lang),
                aria_label=translate("chart.seasonal_aria", lang),
                y_max=sections["seasonal"]["y_max"],
                label_step=2,
                x_label=translate("chart.season_x", lang),
                y_label=translate("chart.precip_mm", lang),
            )
            if sections["seasonal"]
            else "",
            "november": charts.bar_chart(
                sections["november"]["bars"],
                line=sections["november"]["trend_line"],
                line_label=translate("chart.sen_trend", lang),
                aria_label=translate("chart.november_aria", lang),
                y_max=sections["november"]["y_max"],
                label_step=2,
                x_label=translate("chart.year_x", lang),
                y_label=translate("chart.november_y", lang),
            )
            if sections["november"]
            else "",
            "climatology": charts.band_chart(
                sections["climatology"],
                aria_label=translate("chart.climatology_aria", lang),
                x_label=translate("chart.month_x", lang),
                y_label=translate("chart.monthly_y", lang),
            )
            if sections["climatology"]
            else "",
            "onset": charts.strip_chart(
                sections["onset"]["rows"],
                aria_label=translate("chart.onset_aria", lang),
                median=sections["onset"]["median"],
                x_label=translate("chart.onset_x", lang),
                y_label=translate("chart.season_x", lang),
            )
            if sections["onset"] and sections["onset"]["median"] is not None
            else "",
            "comparison": charts.error_bar_chart(
                sections["comparison"]["groups"],
                aria_label=translate("chart.comparison_aria", lang),
                x_label=translate("chart.period_x", lang),
                y_label=translate("chart.mean_y", lang),
            )
            if sections["comparison"]
            else "",
            "importances": charts.hbar_chart(
                sections["model"]["importances"],
                aria_label=translate("chart.importance_aria", lang),
                x_label=translate("chart.importance_x", lang),
                y_label=translate("chart.variable_y", lang),
            )
            if sections["model"] and sections["model"]["importances"]
            else "",
        }
        return render_template(
            "analysis.html",
            sections=sections,
            charts=charts_out,
        )

    @app.route("/sobre")
    def about():
        return render_template("about.html")

    with app.app_context():
        if not app.config["IS_VERCEL"]:
            db.create_all()
        if (
            not app.config["IS_VERCEL"]
            and app.config.get("AUTO_TRAIN_MODEL", True)
        ):
            from .services.training import ensure_trained_model

            try:
                metadata = ensure_trained_model()
            except Exception as exc:  # heuristic fallback keeps the app usable
                app.logger.warning("Onset model training skipped: %s", exc)
            else:
                if metadata:
                    app.logger.info(
                        "Onset model active: %s", metadata.get("version")
                    )

    return app
