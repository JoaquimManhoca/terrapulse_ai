"""Tests for the Harmony-based remote ingestion (no network: fake client)."""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr

from app.ml.persistence import MODEL_VERSION
from app.services import harmony_ingest
from tests.test_ingest import LAT, LON


def _write_season_granule(directory: Path, season_year: int) -> Path:
    """Fake Harmony subset for one season: Oct 1 .. Mar 31."""
    start = date(season_year, 10, 1)
    days = [start + timedelta(days=i) for i in range(183)]
    values = np.full((len(days), len(LON), len(LAT)), 0.0, dtype=np.float32)
    for index, day in enumerate(days):
        if day.month == 11 and day.day <= 3:
            values[index, :, :] = 10.0
        elif day.month == 11 and day.day <= 24:
            values[index, :, :] = 2.0
    ds = xr.Dataset(
        {"precipitation": (("time", "lon", "lat"), values)},
        coords={
            "time": [np.datetime64(day) for day in days],
            "lon": LON,
            "lat": LAT,
        },
        attrs={"BeginDate": days[0].isoformat(), "title": "fake Harmony subset"},
    )
    ds["precipitation"].attrs["units"] = "mm/day"
    path = directory / f"harmony-{season_year}.nc4"
    ds.to_netcdf(path)
    ds.close()
    return path


class _FakeFuture:
    def __init__(self, path: Path):
        self._path = path

    def result(self) -> Path:
        return self._path


class FakeClient:
    """Deterministic stand-in for harmony.Client (no network)."""

    def __init__(self, directory: Path, seasons: list[int], polls: int = 2):
        self._directory = directory
        self._seasons = seasons
        self._polls_needed = polls
        self._polls: dict[str, int] = {}
        self._jobs = 0
        self.canceled: list[str] = []
        self.submitted = 0

    def submit(self, request) -> str:
        self.submitted += 1
        job_id = f"job-{self.submitted}"
        self._polls[job_id] = 0
        return job_id

    def status(self, job_id: str) -> dict:
        self._polls[job_id] += 1
        if self._polls[job_id] >= self._polls_needed:
            return {"status": "successful", "progress": 100}
        return {"status": "running", "progress": 50}

    def download_all(self, job_id: str, directory, overwrite: bool = True):
        season = self._seasons[(int(job_id.split("-")[1]) - 1) % len(self._seasons)]
        path = _write_season_granule(Path(directory), season)
        return [_FakeFuture(path)]

    def cancel(self, job_id: str) -> None:
        self.canceled.append(job_id)


@pytest.fixture()
def harmony_env(monkeypatch):
    harmony_ingest.reset_state()
    monkeypatch.setattr(harmony_ingest, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(
        harmony_ingest, "_collection_coverage", lambda: None
    )
    yield
    harmony_ingest.reset_state()


def test_complete_seasons_support_windows():
    seasons = harmony_ingest._complete_seasons(
        date(2022, 1, 1), date(2024, 6, 1)
    )
    # 2022 (Oct 2022 - Mar 2023 + windows) and 2023 (Oct 2023 - Apr 2024).
    assert [year for year, _, _ in seasons] == [2022, 2023]
    assert seasons[0][1] == date(2022, 9, 2)
    assert seasons[0][2] == date(2023, 4, 21)


def test_start_validates_range(app):
    with app.app_context():
        with pytest.raises(ValueError, match="on or after"):
            harmony_ingest.start_harmony_ingest(
                date(2024, 1, 1), date(2023, 1, 1)
            )
        with pytest.raises(ValueError, match="complete rainy season"):
            harmony_ingest.start_harmony_ingest(
                date(2024, 5, 1), date(2024, 9, 1)
            )


def test_harmony_ingest_runs_and_retrains(client, monkeypatch, tmp_path, harmony_env):
    fake = FakeClient(tmp_path, seasons=[2023], polls=2)
    monkeypatch.setattr(harmony_ingest, "_earthdata_client", lambda: fake)

    response = client.post(
        "/api/admin/ingest-harmony",
        json={"start_date": "2023-01-01", "end_date": "2024-06-01"},
    )
    assert response.status_code == 202
    assert response.get_json()["seasons_total"] == 1

    deadline = time.time() + 60
    status = {}
    while time.time() < deadline:
        status = client.get("/api/admin/ingest-harmony/status").get_json()
        if not status["running"]:
            break
        time.sleep(0.05)

    assert status["running"] is False
    assert status["error"] is None
    assert status["seasons_total"] == 1
    assert status["seasons_done"] == 1
    assert status["seasons_completed"] == 1
    # The fixture has the same dates, so Harmony refreshes those observations.
    assert status["days_updated"] == 183
    assert status["days_ingested"] == 0
    assert status["model_version"] == MODEL_VERSION

    decision = client.get("/api/decision").get_json()
    assert decision["model_version"] == MODEL_VERSION


def test_second_ingest_while_running_is_rejected(
    client, monkeypatch, tmp_path, harmony_env
):
    fake = FakeClient(tmp_path, seasons=[2023], polls=10_000)
    monkeypatch.setattr(harmony_ingest, "_earthdata_client", lambda: fake)
    monkeypatch.setattr(harmony_ingest, "SEASON_TIMEOUT_SECONDS", 1.0)

    first = client.post(
        "/api/admin/ingest-harmony",
        json={"start_date": "2023-01-01", "end_date": "2024-06-01"},
    )
    assert first.status_code == 202

    second = client.post(
        "/api/admin/ingest-harmony",
        json={"start_date": "2023-01-01", "end_date": "2024-06-01"},
    )
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "already_running"

    deadline = time.time() + 30
    status = {}
    while time.time() < deadline:
        status = client.get("/api/admin/ingest-harmony/status").get_json()
        if not status["running"]:
            break
        time.sleep(0.05)

    assert status["running"] is False
    assert any("timed out" in error for error in status["errors"])
    assert fake.canceled


def test_missing_credentials_reports_error(app, monkeypatch, harmony_env):
    def _no_credentials():
        raise RuntimeError("Earthdata Login is not configured.")

    monkeypatch.setattr(harmony_ingest, "_earthdata_client", _no_credentials)

    with app.app_context():
        harmony_ingest.start_harmony_ingest(date(2022, 1, 1), date(2024, 6, 1))
        deadline = time.time() + 10
        status = {}
        while time.time() < deadline:
            status = harmony_ingest.harmony_ingest_status()
            if not status["running"]:
                break
            time.sleep(0.05)

    assert status["running"] is False
    assert "Earthdata" in status["error"]


def test_range_is_clamped_to_collection_coverage(app, monkeypatch, harmony_env):
    monkeypatch.setattr(
        harmony_ingest,
        "_collection_coverage",
        lambda: (date(1998, 1, 1), date(2024, 9, 30)),
    )
    monkeypatch.setattr(
        harmony_ingest,
        "_earthdata_client",
        lambda: (_ for _ in ()).throw(RuntimeError("no client in this test")),
    )

    with app.app_context():
        status = harmony_ingest.start_harmony_ingest()
        assert status["requested_end"] == "2024-09-30"
        # end clamped to 2024-09-30: last complete season is 2023
        # (Oct 2023 - Mar 2024, support to 2024-04-21)
        assert status["seasons_total"] == 26  # 1998..2023

        deadline = time.time() + 10
        final = {}
        while time.time() < deadline:
            final = harmony_ingest.harmony_ingest_status()
            if not final["running"]:
                break
            time.sleep(0.05)

    assert final["running"] is False
    assert "no client in this test" in final["error"]
