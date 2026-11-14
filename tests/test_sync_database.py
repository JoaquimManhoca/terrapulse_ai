from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import DailyObservation
from scripts.sync_database import sync_observations


def _sqlite_url(path) -> str:
    return "sqlite:///" + path.resolve().as_posix()


def test_sync_copies_only_real_rows_and_is_idempotent(tmp_path):
    source_engine = create_engine(_sqlite_url(tmp_path / "source.db"))
    target_engine = create_engine(_sqlite_url(tmp_path / "target.db"))
    db.metadata.create_all(source_engine)
    db.metadata.create_all(target_engine)

    with Session(source_engine) as session:
        session.add_all(
            [
                DailyObservation(
                    day=date(2025, 1, 1),
                    precip_mm=4.0,
                    coverage_pct=100.0,
                    source="imerg_early_daily",
                    qc_flag="imerg_bbox_mean",
                ),
                DailyObservation(
                    day=date(2025, 1, 2),
                    precip_mm=8.0,
                    coverage_pct=100.0,
                    source="synthetic",
                    qc_flag="synthetic",
                ),
            ]
        )
        session.commit()

    with Session(target_engine) as session:
        session.add(
            DailyObservation(
                day=date(2025, 1, 3),
                precip_mm=3.0,
                coverage_pct=100.0,
                source="synthetic",
                qc_flag="synthetic",
            )
        )
        session.commit()

    try:
        first = sync_observations(
            _sqlite_url(tmp_path / "source.db"),
            _sqlite_url(tmp_path / "target.db"),
        )
        assert first == {
            "source_rows": 1,
            "inserted": 1,
            "updated": 0,
            "non_real_deleted": 1,
        }

        with Session(source_engine) as session:
            row = session.scalar(
                select(DailyObservation).where(
                    DailyObservation.day == date(2025, 1, 1)
                )
            )
            row.precip_mm = 9.0
            session.commit()

        second = sync_observations(
            _sqlite_url(tmp_path / "source.db"),
            _sqlite_url(tmp_path / "target.db"),
        )
        assert second["inserted"] == 0
        assert second["updated"] == 1
        assert second["non_real_deleted"] == 0

        with Session(target_engine) as session:
            rows = session.scalars(select(DailyObservation)).all()
            assert len(rows) == 1
            assert rows[0].source == "imerg_early_daily"
            assert rows[0].precip_mm == 9.0
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_sync_purges_non_imerg_rows_when_source_is_empty(tmp_path):
    source_engine = create_engine(_sqlite_url(tmp_path / "empty.db"))
    target_engine = create_engine(_sqlite_url(tmp_path / "target.db"))
    db.metadata.create_all(source_engine)
    db.metadata.create_all(target_engine)

    with Session(source_engine) as session:
        session.add(
            DailyObservation(
                day=date(2025, 1, 1),
                precip_mm=4.0,
                coverage_pct=100.0,
                source="synthetic",
                qc_flag="synthetic",
            )
        )
        session.commit()
    with Session(target_engine) as session:
        session.add(
            DailyObservation(
                day=date(2025, 1, 2),
                precip_mm=2.0,
                coverage_pct=100.0,
                source="synthetic",
                qc_flag="synthetic",
            )
        )
        session.commit()

    try:
        result = sync_observations(
            _sqlite_url(tmp_path / "empty.db"),
            _sqlite_url(tmp_path / "target.db"),
        )
        assert result["source_rows"] == 0
        assert result["non_real_deleted"] == 1
        with Session(target_engine) as session:
            assert session.query(DailyObservation).count() == 0
    finally:
        source_engine.dispose()
        target_engine.dispose()
