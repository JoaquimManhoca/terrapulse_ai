from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from app.extensions import db
from app.models import DailyObservation
from app.services.ingest import (
    discover_files,
    ingest_imerg,
    read_manica_day,
    read_manica_days,
)
from app.services.series_service import data_status

LON = np.round(np.arange(32.65, 33.21, 0.1), 2)
LAT = np.round(np.arange(-19.15, -18.61, 0.1), 2)


def _write_granule(tmp_path: Path, day: str = "2025-12-11", nan_at=None) -> Path:
    values = np.full((1, len(LON), len(LAT)), 2.0, dtype=np.float32)
    if nan_at is not None:
        values[0, nan_at[0], nan_at[1]] = np.nan
    ds = xr.Dataset(
        {"precipitation": (("time", "lon", "lat"), values)},
        coords={
            "time": [np.datetime64(day)],
            "lon": LON,
            "lat": LAT,
        },
        attrs={"BeginDate": day, "title": "test IMERG granule"},
    )
    ds["precipitation"].attrs["units"] = "mm/day"
    path = tmp_path / (
        f"3B-DAY-E.MS.MRG.3IMERG.{day.replace('-', '')}-S000000-E235959.V07B.nc4"
    )
    ds.to_netcdf(path)
    ds.close()
    return path


def _write_multi_granule(
    tmp_path: Path,
    days: list[str],
    values: list[float],
) -> Path:
    data = np.stack(
        [np.full((len(LON), len(LAT)), value, dtype=np.float32) for value in values]
    )
    ds = xr.Dataset(
        {"precipitation": (("time", "lon", "lat"), data)},
        coords={
            "time": [np.datetime64(day) for day in days],
            "lon": LON,
            "lat": LAT,
        },
        attrs={"BeginDate": days[0], "title": "test IMERG multi-day granule"},
    )
    ds["precipitation"].attrs["units"] = "mm/day"
    path = tmp_path / "subset-multi-day.nc4"
    ds.to_netcdf(path)
    ds.close()
    return path


def test_read_manica_day_bbox_mean(tmp_path):
    path = _write_granule(tmp_path)
    day = read_manica_day(path)
    assert day.day == date(2025, 12, 11)
    assert day.precip_mm == pytest.approx(2.0)
    assert day.coverage_pct == pytest.approx(100.0)
    assert day.qc_flag == "imerg_bbox_mean"


def test_read_manica_day_partial_coverage(tmp_path):
    path = _write_granule(tmp_path, nan_at=(1, 1))
    day = read_manica_day(path)
    assert day.precip_mm == pytest.approx(2.0)
    assert day.coverage_pct == pytest.approx(95.0)
    assert day.qc_flag == "imerg_partial"


def test_read_manica_days_multi_time(tmp_path):
    path = _write_multi_granule(
        tmp_path,
        ["2025-12-11", "2025-12-12"],
        [2.0, 5.0],
    )
    days = read_manica_days(path)
    assert [item.day for item in days] == [
        date(2025, 12, 11),
        date(2025, 12, 12),
    ]
    assert [item.precip_mm for item in days] == [
        pytest.approx(2.0),
        pytest.approx(5.0),
    ]
    assert all(item.coverage_pct == pytest.approx(100.0) for item in days)


def test_read_manica_day_rejects_multi_time(tmp_path):
    path = _write_multi_granule(
        tmp_path,
        ["2025-12-11", "2025-12-12"],
        [2.0, 5.0],
    )
    with pytest.raises(ValueError):
        read_manica_day(path)


def test_ingest_multi_time_file(app, tmp_path):
    _write_multi_granule(
        tmp_path,
        ["2025-12-11", "2025-12-12"],
        [2.0, 5.0],
    )
    with app.app_context():
        result = ingest_imerg(tmp_path)
        assert result.ingested == 2

        rows = (
            db.session.query(DailyObservation)
            .filter(
                DailyObservation.day.in_(
                    [date(2025, 12, 11), date(2025, 12, 12)]
                )
            )
            .order_by(DailyObservation.day)
            .all()
        )
        assert [row.precip_mm for row in rows] == [
            pytest.approx(2.0),
            pytest.approx(5.0),
        ]


def test_discover_files_ignores_partial_downloads(tmp_path):
    _write_granule(tmp_path)
    (tmp_path / "Unconfirmed 123.crdownload").write_bytes(b"partial")
    files = discover_files(tmp_path)
    assert len(files) == 1
    assert files[0].suffix == ".nc4"


def test_ingest_replaces_synthetic_day(app, tmp_path):
    path = _write_granule(tmp_path)
    assert path.exists()
    with app.app_context():
        db.session.add(
            DailyObservation(
                day=date(2025, 12, 11),
                precip_mm=99.0,
                coverage_pct=100.0,
                source="synthetic",
                qc_flag="synthetic",
            )
        )
        db.session.commit()

        result = ingest_imerg(tmp_path)
        assert result.updated == 1
        assert result.ingested == 0

        row = (
            db.session.query(DailyObservation)
            .filter_by(day=date(2025, 12, 11))
            .one()
        )
        assert row.source == "imerg_early_daily"
        assert row.precip_mm == pytest.approx(2.0)
        assert row.qc_flag == "imerg_bbox_mean"
        assert data_status() == "real"


def test_ingest_marks_real_when_no_synthetic(app, tmp_path):
    _write_granule(tmp_path)
    with app.app_context():
        db.session.query(DailyObservation).delete()
        db.session.commit()

        result = ingest_imerg(tmp_path)
        assert result.ingested == 1
        assert data_status() == "real"


def test_ingest_deduplicates_same_date(app, tmp_path):
    source = _write_granule(tmp_path)
    duplicate = tmp_path / source.name.replace(".nc4", " (1).nc4")
    duplicate.write_bytes(source.read_bytes())
    with app.app_context():
        result = ingest_imerg(tmp_path)
        assert result.ingested == 1
        assert result.skipped == 1


def test_ingest_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        ingest_imerg(tmp_path / "does-not-exist")


