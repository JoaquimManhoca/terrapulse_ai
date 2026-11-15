"""Flask CLI commands."""

from __future__ import annotations

import csv
from pathlib import Path

import click
from sqlalchemy import func, inspect


def register_cli(app) -> None:
    @app.cli.command("init-db")
    def init_db() -> None:
        from .extensions import db

        db.create_all()
        click.echo("Database tables are ready.")

    @app.cli.command("upgrade-feedback-schema")
    def upgrade_feedback_schema() -> None:
        from .extensions import db
        from .models import DecisionFeedback

        table = DecisionFeedback.__table__
        inspector = inspect(db.engine)
        if not inspector.has_table(table.name):
            table.create(db.engine, checkfirst=True)
        else:
            columns = {
                column["name"] for column in inspector.get_columns(table.name)
            }
            if "submission_id" not in columns:
                with db.engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE decision_feedback "
                        "ADD COLUMN submission_id VARCHAR(36)"
                    )

        inspector = inspect(db.engine)
        index_names = {
            index["name"] for index in inspector.get_indexes(table.name)
        }
        index_name = "uq_decision_feedback_submission_id"
        if index_name not in index_names:
            with db.engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_decision_feedback_submission_id "
                    "ON decision_feedback (submission_id)"
                )
        click.echo("Feedback schema is ready.")

    @app.cli.command("feedback-summary")
    def feedback_summary() -> None:
        from .extensions import db
        from .models import DecisionFeedback

        total = db.session.query(func.count(DecisionFeedback.id)).scalar()
        click.echo(f"Total responses: {total or 0}")
        dimensions = (
            ("choice", DecisionFeedback.choice),
            ("decision state", DecisionFeedback.state),
            ("region", DecisionFeedback.region),
            ("crop", DecisionFeedback.crop),
            ("language", DecisionFeedback.lang),
        )
        for label, column in dimensions:
            click.echo(f"By {label}:")
            rows = (
                db.session.query(column, func.count(DecisionFeedback.id))
                .group_by(column)
                .order_by(column)
                .all()
            )
            if not rows:
                click.echo("  (none)")
            for value, count in rows:
                click.echo(f"  {value}: {count}")

    @app.cli.command("feedback-export")
    @click.option(
        "--output",
        default="-",
        show_default=True,
        help="CSV file path, or - for standard output.",
    )
    def feedback_export(output: str) -> None:
        from .extensions import db
        from .models import DecisionFeedback

        fields = (
            "id",
            "created_at",
            "decision_date",
            "choice",
            "state",
            "confidence",
            "model_version",
            "last_observation",
            "region",
            "crop",
            "lang",
        )

        def spreadsheet_safe(value):
            if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(
                ("=", "+", "-", "@")
            ):
                return "'" + value
            return value

        def write_csv(stream) -> None:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            records = (
                DecisionFeedback.query.order_by(
                    DecisionFeedback.created_at,
                    DecisionFeedback.id,
                )
                .yield_per(500)
            )
            for record in records:
                row = record.to_dict()
                writer.writerow(
                    {
                        field: spreadsheet_safe(row.get(field))
                        for field in fields
                    }
                )

        if output == "-":
            write_csv(click.get_text_stream("stdout"))
        else:
            with Path(output).open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                write_csv(stream)
            click.echo(f"Feedback exported to {output}", err=True)

    @app.cli.command("ingest")
    @click.option("--dir", "directory", default=None, help="Directory with IMERG .nc4 files.")
    @click.option("--pattern", default=None, help="Glob pattern (default *.nc4).")
    def ingest(directory: str | None, pattern: str | None) -> None:
        from .services.ingest import ingest_imerg

        result = ingest_imerg(
            Path(directory) if directory else app.config["INGEST_DIR"],
            pattern or app.config["IMERG_PATTERN"],
        )
        click.echo(
            f"Ingested {result.ingested}, updated {result.updated}, "
            f"skipped {result.skipped}, errors {len(result.errors)}."
        )
        for error in result.errors[:10]:
            click.echo(f"  - {error}")

    @app.cli.command("train")
    @click.option(
        "--force",
        is_flag=True,
        help="Retrain and overwrite the persisted model.",
    )
    def train(force: bool) -> None:
        from .services.training import ensure_trained_model, train_and_persist

        try:
            record = train_and_persist() if force else ensure_trained_model()
        except ValueError as exc:
            click.echo(f"Training failed: {exc}")
            raise SystemExit(1)
        if record is None:
            click.echo("No model available.")
            return
        click.echo(f"Model {record['version']} saved at {record['saved_at']}.")
        for split, metrics in (record.get("metrics") or {}).items():
            click.echo(
                f"  {split}: rows={metrics['rows']} "
                f"accuracy={metrics['accuracy']:.3f} f1={metrics['f1']:.3f} "
                f"roc_auc={metrics['roc_auc']}"
            )
