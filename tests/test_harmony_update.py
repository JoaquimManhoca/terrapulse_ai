"""Tests for incremental Harmony updates (no network: fake client)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

from app.extensions import db
from app.models import DailyObservation
from app.services import harmony_update
from tests.test_ingest import LAT, LON


def test_date_chunks_cover_the_range():
    chunks = harmony_update.date_chunks(
        date(2026, 10, 1), date(2026, 11, 13), chunk_days=31
    )

    assert chunks == [
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 11, 1), date(2026, 11, 13)),
    ]


def test_update_early_is_noop_when_coverage_has_no_new_day(monkeypatch):
    monkeypatch.setattr(
        harmony_update,
        "collection_coverage",
        lambda collection_id: (date(2025, 1, 1), date(2025, 1, 5)),
    )

    result = harmony_update.update_early(date(2025, 1, 6), date(2025, 1, 7))

    assert result.days_requested == 0
    assert result.errors == []


class _FakeFuture:
    def __init__(self, path: Path):
        self._path = path

    def result(self) -> Path:
        return self._path


class FakeClient:
    def __init__(self, directory: Path, days: list[date]):
        self._directory = directory
        self._days = days
        self.submitted = 0

    def submit(self, request) -> str:
        self.submitted += 1
        return f"job-{self.submitted}"

    def status(self, job_id: str) -> dict:
        return {"status": "successful"}

    def download_all(self, job_id: str, directory, overwrite: bool = True):
        values = np.full(
            (len(self._days), len(LON), len(LAT)), 4.0, dtype=np.float32
        )
        dataset = xr.Dataset(
            {"precipitation": (("time", "lon", "lat"), values)},
            coords={
                "time": [np.datetime64(day) for day in self._days],
                "lon": LON,
                "lat": LAT,
            },
        )
        path = Path(directory) / "harmony-update.nc4"
        dataset.to_netcdf(path)
        dataset.close()
        return [_FakeFuture(path)]


def test_update_early_ingests_and_protects_final(app, monkeypatch, tmp_path):
    days = [date(2025, 1, 1) + timedelta(days=index) for index in range(3)]
    monkeypatch.setattr(
        harmony_update,
        "collection_coverage",
        lambda collection_id: (date(2025, 1, 1), date(2025, 1, 10)),
    )

    with app.app_context():
        db.session.add(
            DailyObservation(
                day=days[1],
                precip_mm=99.0,
                coverage_pct=100.0,
                source="imerg_final_daily",
                qc_flag="imerg_bbox_mean",
            )
        )
        db.session.commit()

        result = harmony_update.update_early(
            date(2025, 1, 1),
            date(2025, 1, 3),
            client=FakeClient(tmp_path, days),
            chunk_days=3,
            poll_seconds=0.01,
        )

        assert result.days_ingested == 2
        assert result.jobs_completed == 1
        stored = {
            row.day: row
            for row in db.session.query(DailyObservation)
            .filter(DailyObservation.day.in_(days))
            .all()
        }
        assert stored[days[1]].source == "imerg_final_daily"
        assert stored[days[1]].precip_mm == 99.0
        assert stored[days[0]].source == "imerg_early_daily"
