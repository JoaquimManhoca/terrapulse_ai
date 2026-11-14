"""TerraPulse AI application package."""

from __future__ import annotations

from flask import (
    Flask,
    current_app,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from .config import Config
from .extensions import cors, db
from .i18n import LANGUAGES, SUPPORTED_LANGUAGES, get_catalog, translate


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith(
        "postgresql+psycopg://"
    ):
        engine_options = dict(app.config["SQLALCHEMY_ENGINE_OPTIONS"])
        connect_args = dict(engine_options.get("connect_args", {}))
        connect_args["prepare_threshold"] = None
        engine_options["connect_args"] = connect_args
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options

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

    @app.route("/language/<lang_code>")
    def set_language(lang_code: str):
        if lang_code in SUPPORTED_LANGUAGES:
            session["lang"] = lang_code
        return redirect(request.referrer or url_for("index"))

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
            regions=regions,
            crops=crops,
            selected_region=region,
            selected_crop=crop,
            selection_supported=supported,
        )

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
            seasons=season_monthly_totals(),
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

        sections = {
            "seasonal": seasonal_view(),
            "november": november_view(),
            "climatology": climatology_view(),
            "onset": onset_calendar_view(),
            "comparison": period_comparison_view(),
            "model": model_view(),
        }
        charts_out = {
            "seasonal": charts.bar_chart(
                sections["seasonal"]["bars"],
                line=sections["seasonal"]["trend_line"],
                line_label="Tendência (Sen)",
                aria_label="Total de chuva por época chuvosa, 1998 a 2024",
                y_max=sections["seasonal"]["y_max"],
                label_step=2,
            )
            if sections["seasonal"]
            else "",
            "november": charts.bar_chart(
                sections["november"]["bars"],
                line=sections["november"]["trend_line"],
                line_label="Tendência (Sen)",
                aria_label="Total de chuva de novembro por época",
                y_max=sections["november"]["y_max"],
                label_step=2,
            )
            if sections["november"]
            else "",
            "climatology": charts.band_chart(
                sections["climatology"],
                aria_label="Climatologia mensal da época chuvosa",
            )
            if sections["climatology"]
            else "",
            "onset": charts.strip_chart(
                sections["onset"]["rows"],
                aria_label="Dia do início efetivo da chuva por época",
                median=sections["onset"]["median"],
            )
            if sections["onset"] and sections["onset"]["median"] is not None
            else "",
            "comparison": charts.error_bar_chart(
                sections["comparison"]["groups"],
                aria_label="Comparação da média de chuva entre períodos",
            )
            if sections["comparison"]
            else "",
            "importances": charts.hbar_chart(
                sections["model"]["importances"],
                aria_label="Importância das variáveis no modelo Random Forest",
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
