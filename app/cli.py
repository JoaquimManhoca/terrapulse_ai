"""Flask CLI commands."""

from __future__ import annotations

from pathlib import Path

import click


def register_cli(app) -> None:
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
