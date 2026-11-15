r"""Bring the local IMERG series and Supabase up to date.

Downloads IMERG Early Daily for the missing period through NASA Harmony
(server-side bbox subsetting), ingests it into the local SQLite database,
optionally retrains the onset model, and syncs the real observations to the
PostgreSQL/Supabase database configured in ``DATABASE_URL``.

Examples:
    .\.venv\Scripts\python.exe scripts\update_data.py
    .\.venv\Scripts\python.exe scripts\update_data.py --start 2025-10-01
    .\.venv\Scripts\python.exe scripts\update_data.py --no-sync --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _sqlite_url(path: Path) -> str:
    return "sqlite:///" + path.resolve().as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        help="First missing day (YYYY-MM-DD). Default: day after the last row.",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="Last day (YYYY-MM-DD). Default: yesterday (Early lag).",
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=ROOT / "data" / "terrapulse.db",
        help="Local SQLite database to update.",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=31,
        help="Days per Harmony job. Default: 31.",
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Retrain and persist the onset model after ingesting.",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Do not copy the observations to DATABASE_URL (PostgreSQL).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the range and exit without downloading.",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    target_url = os.getenv("DATABASE_URL")

    # The local app must write SQLite during ingestion; the target database is
    # synced explicitly at the end.
    os.environ["DATABASE_URL"] = _sqlite_url(args.sqlite)
    os.environ["AUTO_TRAIN_MODEL"] = "0"

    from sqlalchemy import func

    from app import create_app
    from app.extensions import db
    from app.models import DailyObservation
    from app.services.harmony_update import update_early

    app = create_app()
    with app.app_context():
        db.create_all()
        last_day = db.session.query(func.max(DailyObservation.day)).scalar()
        end = args.end or (date.today() - timedelta(days=1))
        start = args.start or (
            last_day + timedelta(days=1)
            if last_day is not None
            else end - timedelta(days=30)
        )
        if end < start:
            print(f"Nothing to do: {start} is after {end}.")
            return 0

        print(
            f"IMERG Early update {start}..{end} "
            f"({(end - start).days + 1} days, chunks of {args.chunk_days})."
        )
        print(f"Local SQLite: {args.sqlite}")
        if args.dry_run:
            return 0

        def report(result) -> None:
            print(
                f"  chunks done: {result.jobs_completed}/"
                f"{result.jobs_submitted}, "
                f"+{result.days_ingested} new, "
                f"{result.days_updated} refreshed."
            )

        result = update_early(
            start,
            end,
            chunk_days=args.chunk_days,
            progress=report,
        )
        summary = result.as_dict()
        print(
            f"Update finished: {summary['days_ingested']} inserted, "
            f"{summary['days_updated']} updated, "
            f"{summary['jobs_completed']}/{summary['jobs_submitted']} jobs."
        )
        for error in result.errors[:10]:
            print(f"  - {error}")

        if args.retrain:
            from app.services.training import train_and_persist

            try:
                record = train_and_persist()
            except ValueError as exc:
                print(f"Training skipped: {exc}")
            else:
                print(
                    f"Model {record['version']} saved at {record['saved_at']}."
                )

    if not args.no_sync and target_url and target_url.startswith(
        ("postgres://", "postgresql://")
    ):
        from scripts.sync_database import sync_observations

        sync = sync_observations(_sqlite_url(args.sqlite), target_url)
        print(
            f"Supabase sync: {sync['source_rows']} real rows, "
            f"{sync['inserted']} inserted, {sync['updated']} updated, "
            f"{sync['non_real_deleted']} non-IMERG removed."
        )
    elif not args.no_sync:
        print("No PostgreSQL DATABASE_URL configured; skipped Supabase sync.")

    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
