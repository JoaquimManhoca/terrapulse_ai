"""Copy real IMERG observations from the local SQLite database to PostgreSQL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Config, _engine_options
from app.extensions import db
from app.models import DailyObservation

REAL_SOURCES = ("imerg_early_daily", "imerg_final_daily")
_BATCH_SIZE = 500
_OBSERVATION_FIELDS = ("day", "precip_mm", "coverage_pct", "source", "qc_flag")


def _sqlite_url(path: Path) -> str:
    return "sqlite:///" + path.resolve().as_posix()


def sync_observations(
    source_url: str,
    target_url: str,
    dry_run: bool = False,
) -> dict[str, int]:
    """Idempotently copy IMERG rows and purge synthetic rows from the target."""
    source_engine = create_engine(source_url)
    target_engine = create_engine(
        target_url,
        **_engine_options(target_url, Config.IS_VERCEL),
    )
    try:
        table = DailyObservation.__table__
        query = (
            select(table)
            .where(table.c.source.in_(REAL_SOURCES))
            .order_by(table.c.day)
        )
        with source_engine.connect() as connection:
            rows = [
                {field: row[field] for field in _OBSERVATION_FIELDS}
                for row in connection.execute(query).mappings()
            ]

        result = {
            "source_rows": len(rows),
            "inserted": 0,
            "updated": 0,
            "non_real_deleted": 0,
        }
        if dry_run:
            return result

        db.metadata.create_all(target_engine)
        with Session(target_engine) as session:
            result["non_real_deleted"] = (
                session.query(DailyObservation)
                .filter(~DailyObservation.source.in_(REAL_SOURCES))
                .delete(synchronize_session=False)
            )
            session.commit()
            for offset in range(0, len(rows), _BATCH_SIZE):
                batch = rows[offset : offset + _BATCH_SIZE]
                days = [row["day"] for row in batch]
                existing = {
                    item.day: item
                    for item in session.scalars(
                        select(DailyObservation).where(
                            DailyObservation.day.in_(days)
                        )
                    )
                }
                for row in batch:
                    observation = existing.get(row["day"])
                    if observation is None:
                        session.add(DailyObservation(**row))
                        result["inserted"] += 1
                    else:
                        for field in _OBSERVATION_FIELDS[1:]:
                            setattr(observation, field, row[field])
                        result["updated"] += 1
                session.commit()
        return result
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Config.DATA_DIR / "terrapulse.db",
        help="Local SQLite file (default: data/terrapulse.db).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count source IMERG rows without writing to PostgreSQL.",
    )
    args = parser.parse_args()

    if not args.source.is_file():
        parser.error(f"Source SQLite database not found: {args.source}")
    target_url = Config.SQLALCHEMY_DATABASE_URI
    if make_url(target_url).get_backend_name() != "postgresql":
        parser.error("Set DATABASE_URL to the persistent PostgreSQL database.")

    result = sync_observations(_sqlite_url(args.source), target_url, args.dry_run)
    action = "Dry run" if args.dry_run else "Sync complete"
    print(
        f"{action}: {result['source_rows']} real IMERG rows, "
        f"{result['inserted']} inserted, {result['updated']} updated, "
        f"{result['non_real_deleted']} non-IMERG rows removed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
