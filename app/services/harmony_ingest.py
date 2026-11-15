"""Remote IMERG Final ingestion through NASA Harmony.

NASA subsets the data server-side: only the Manica bbox, only the
``precipitation`` variable, only complete rainy seasons. Instead of
downloading hundreds of GB of global granules, each season transfers a
NetCDF file of a few hundred KB.

The ingestion runs in a background thread: it submits up to
``MAX_CONCURRENT_JOBS`` Harmony jobs, polls them, writes each completed
season to SQLite via ``upsert_observations`` and, at the end, retrains the
onset classifier. Progress is exposed through ``harmony_ingest_status``.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
import traceback
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import current_app
from harmony import BBox, Client, Collection, Request

from ..config import Config
from ..extensions import db
from .earthdata import collection_coverage as _cmr_collection_coverage
from .earthdata import earthdata_client as _earthdata_client
from .ingest import (
    FINAL_SOURCE,
    IngestedDay,
    read_manica_days,
    upsert_observations,
)
from .training import train_and_persist

COLLECTION_ID = "C2723754864-GES_DISC"
DEFAULT_START = date(1998, 1, 1)
DOWNLOAD_RETRIES = 5
DOWNLOAD_WORKERS = 3
FINAL_LAG_DAYS = 120
MAX_CONCURRENT_JOBS = 8
POLL_SECONDS = 15
SEASON_TIMEOUT_SECONDS = 45 * 60
SUBMIT_RETRIES = 3
TERMINAL_STATES = {"successful", "failed", "canceled"}

_LOCK = threading.RLock()
_DB_WRITE_LOCK = threading.Lock()
_STATE: dict = {}


def reset_state() -> None:
    """Clear the ingest state (used by tests and admin reset)."""
    with _LOCK:
        _STATE.clear()


def _fresh_state() -> dict:
    with _LOCK:
        _STATE.clear()
        _STATE.update(
            {
                "running": True,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": None,
                "error": None,
                "requested_start": None,
                "requested_end": None,
                "collection_coverage": None,
                "seasons_total": 0,
                "seasons_done": 0,
                "seasons_completed": 0,
                "seasons_completed_years": [],
                "current_jobs": 0,
                "downloads_pending": 0,
                "days_ingested": 0,
                "days_updated": 0,
                "errors": [],
                "model_version": None,
                "model_error": None,
            }
        )
        return dict(_STATE)


def harmony_ingest_status() -> dict:
    """Snapshot of the running (or last) Harmony ingestion."""
    with _LOCK:
        status = dict(_STATE)
    status["errors"] = list(status.get("errors") or [])
    status["seasons_completed_years"] = list(
        status.get("seasons_completed_years") or []
    )
    total = status.get("seasons_total") or 0
    done = status.get("seasons_done") or 0
    status["progress_pct"] = round(100.0 * done / total, 1) if total else 0.0
    return status


def _collection_coverage() -> tuple[date, date] | None:
    """First/last granule dates of the collection, via CMR (cached).

    The IMERG Final archive lags production and can pause; clamping the
    requested range avoids seasons that would silently come back partial.
    """
    cached = _STATE.get("collection_coverage")
    if cached:
        return date.fromisoformat(cached[0]), date.fromisoformat(cached[1])
    coverage = _cmr_collection_coverage(COLLECTION_ID)
    if coverage is None:
        return None
    first_day, last_day = coverage
    with _LOCK:
        _STATE["collection_coverage"] = [
            first_day.isoformat(),
            last_day.isoformat(),
        ]
    return coverage


def _complete_seasons(
    start: date, end: date
) -> list[tuple[int, date, date]]:
    """Complete rainy seasons (with support windows) fully inside the range."""
    seasons = []
    for year in range(start.year, end.year + 1):
        season_start = date(year, 10, 1)
        season_end = date(year + 1, 3, 31)
        request_start = season_start - timedelta(days=29)
        request_end = season_end + timedelta(days=Config.ONSET_HORIZON_DAYS)
        if request_start >= start and request_end <= end:
            seasons.append((year, request_start, request_end))
    return seasons


def _season_request(start: date, end: date) -> Request:
    return Request(
        collection=Collection(id=COLLECTION_ID),
        spatial=BBox(*Config.MANICA_BBOX),
        temporal={
            "start": datetime.combine(start, dtime.min),
            "stop": datetime.combine(end, dtime.max).replace(microsecond=0),
        },
        variables=["precipitation"],
        format="application/netcdf",
    )


def _download_days(client: Client, job_id: str) -> list[IngestedDay]:
    """Download the result files of a completed job and parse daily rows."""
    rows_by_day: dict[date, IngestedDay] = {}
    with TemporaryDirectory(prefix=f"harmony-{job_id[:8]}-") as temp_dir:
        downloads = client.download_all(job_id, directory=temp_dir, overwrite=True)
        files = [Path(download.result()) for download in downloads]
        if not files:
            raise RuntimeError("Harmony returned no files.")
        for path in files:
            for observation in read_manica_days(path):
                previous = rows_by_day.get(observation.day)
                if previous is not None and (
                    previous.precip_mm != observation.precip_mm
                    or previous.coverage_pct != observation.coverage_pct
                ):
                    raise ValueError(
                        f"Conflicting Harmony values for {observation.day}."
                    )
                rows_by_day[observation.day] = observation
    return sorted(rows_by_day.values(), key=lambda item: item.day)


def _process_season(
    app, year: int, job_id: str, request_start: date, request_end: date
) -> None:
    """Download + upsert one completed job; runs in a worker thread."""
    with app.app_context():
        try:
            days: list[IngestedDay] | None = None
            last_error: Exception | None = None
            for attempt in range(1, DOWNLOAD_RETRIES + 1):
                try:
                    days = _download_days(_earthdata_client(), job_id)
                    break
                except Exception as exc:  # noqa: BLE001 - retry downloads
                    last_error = exc
                    if attempt < DOWNLOAD_RETRIES:
                        with _LOCK:
                            _STATE["errors"].append(
                                f"season {year}: download attempt {attempt} "
                                f"failed, retrying: {exc}"
                            )
                        time.sleep(min(15 * attempt, 60))
            if days is None:
                raise RuntimeError(
                    f"download failed after {DOWNLOAD_RETRIES} attempts: "
                    f"{last_error}"
                )

            expected = (request_end - request_start).days + 1
            if len(days) < expected:
                with _LOCK:
                    _STATE["errors"].append(
                        f"season {year}: partial coverage "
                        f"{len(days)}/{expected} days"
                    )

            with _DB_WRITE_LOCK:
                ingested, updated, _skipped, _upserted = upsert_observations(
                    days, source=FINAL_SOURCE
                )
                db.session.commit()
            with _LOCK:
                _STATE["days_ingested"] += ingested
                _STATE["days_updated"] += updated
                _STATE["seasons_completed"] += 1
                _STATE["seasons_completed_years"].append(year)
        except Exception as exc:  # noqa: BLE001 - record and keep processing
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass
            with _LOCK:
                _STATE["errors"].append(f"season {year}: {exc}")
        finally:
            with _LOCK:
                _STATE["seasons_done"] += 1
                _STATE["downloads_pending"] -= 1


def _retrain() -> None:
    try:
        record = train_and_persist()
        with _LOCK:
            _STATE["model_version"] = record.get("version")
            _STATE["model_metrics"] = record.get("metrics")
            _STATE["model_error"] = None
    except Exception as exc:  # noqa: BLE001 - decision keeps the heuristic
        with _LOCK:
            _STATE["model_error"] = str(exc)


def _run(app, start: date, end: date) -> None:
    with app.app_context():
        try:
            client = _earthdata_client()
            seasons = _complete_seasons(start, end)
            with _LOCK:
                _STATE["seasons_total"] = len(seasons)

            queue: list[tuple[int, date, date, int]] = [
                (year, request_start, request_end, 1)
                for year, request_start, request_end in seasons
            ]
            active: dict[str, dict] = {}
            downloads = concurrent.futures.ThreadPoolExecutor(
                max_workers=DOWNLOAD_WORKERS, thread_name_prefix="harmony-dl"
            )
            while queue or active:
                while queue and len(active) < MAX_CONCURRENT_JOBS:
                    year, request_start, request_end, attempt = queue.pop(0)
                    try:
                        job_id = client.submit(
                            _season_request(request_start, request_end)
                        )
                        # harmony-py returns the parsed JSON body when the
                        # response is a JSON object; extract or fail loudly.
                        if isinstance(job_id, dict):
                            job_id = job_id.get("jobID")
                        if not isinstance(job_id, str) or not job_id:
                            raise ValueError(
                                f"unexpected submit response: {job_id!r}"
                            )
                    except Exception as exc:  # noqa: BLE001
                        if attempt < SUBMIT_RETRIES:
                            with _LOCK:
                                _STATE["errors"].append(
                                    f"season {year}: submit attempt {attempt} "
                                    f"failed, retrying: {exc}"
                                )
                            queue.append(
                                (year, request_start, request_end, attempt + 1)
                            )
                            time.sleep(5)
                        else:
                            with _LOCK:
                                _STATE["errors"].append(
                                    f"season {year}: submit failed after "
                                    f"{attempt} attempts: {exc}"
                                )
                                _STATE["seasons_done"] += 1
                        continue
                    active[job_id] = {
                        "year": year,
                        "request_start": request_start,
                        "request_end": request_end,
                        "attempt": attempt,
                        "submitted_at": time.monotonic(),
                    }
                    with _LOCK:
                        _STATE["current_jobs"] = len(active)

                for job_id, entry in list(active.items()):
                    year = entry["year"]
                    try:
                        status = client.status(job_id)
                    except Exception:  # noqa: BLE001 - transient network error
                        continue
                    state = status.get("status")
                    if state == "successful":
                        active.pop(job_id)
                        with _LOCK:
                            _STATE["current_jobs"] = len(active)
                            _STATE["downloads_pending"] += 1
                        downloads.submit(
                            _process_season,
                            app,
                            year,
                            job_id,
                            entry["request_start"],
                            entry["request_end"],
                        )
                    elif state in ("failed", "canceled"):
                        active.pop(job_id)
                        with _LOCK:
                            _STATE["current_jobs"] = len(active)
                        attempt = entry.get("attempt", 1)
                        if attempt < SUBMIT_RETRIES:
                            season = next(
                                (
                                    item
                                    for item in seasons
                                    if item[0] == year
                                ),
                                None,
                            )
                            if season is not None:
                                queue.append(
                                    (
                                        year,
                                        season[1],
                                        season[2],
                                        attempt + 1,
                                    )
                                )
                        else:
                            with _LOCK:
                                _STATE["seasons_done"] += 1
                                _STATE["errors"].append(
                                    f"season {year}: {status.get('message', state)}"
                                )
                    elif (
                        time.monotonic() - entry["submitted_at"]
                        > SEASON_TIMEOUT_SECONDS
                    ):
                        active.pop(job_id)
                        with _LOCK:
                            _STATE["current_jobs"] = len(active)
                            _STATE["errors"].append(
                                f"season {year}: Harmony job timed out"
                            )
                            _STATE["seasons_done"] += 1
                        try:
                            client.cancel(job_id)
                        except Exception:  # noqa: BLE001
                            pass

                if queue or active:
                    time.sleep(POLL_SECONDS)

            downloads.shutdown(wait=True)
            _retrain()
        except Exception as exc:  # noqa: BLE001 - surfaced in the status API
            with _LOCK:
                _STATE["error"] = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
        finally:
            with _LOCK:
                _STATE["running"] = False
                _STATE["finished_at"] = datetime.now().isoformat(
                    timespec="seconds"
                )
            db.session.remove()


def start_harmony_ingest(
    start: date | None = None, end: date | None = None
) -> dict:
    """Start the background Harmony ingestion; returns the initial status.

    Raises ValueError on an invalid range and RuntimeError when another
    ingestion is already running. The range is clamped to the collection's
    actual archive coverage (via CMR) so no season is requested partially.
    """
    start = start or DEFAULT_START
    end = end or date.today() - timedelta(days=FINAL_LAG_DAYS)
    if end < start:
        raise ValueError("end must be on or after start")

    with _LOCK:
        if _STATE.get("running"):
            raise RuntimeError("A Harmony ingestion is already running.")
        initial = _fresh_state()

    coverage = _collection_coverage()
    if coverage is not None:
        first_day, last_day = coverage
        if start < first_day:
            start = first_day
        if end > last_day:
            end = last_day

    seasons = _complete_seasons(start, end)
    if not seasons:
        raise ValueError(
            "The requested range does not contain a complete rainy season "
            "plus the required support windows."
        )

    with _LOCK:
        _STATE["requested_start"] = start.isoformat()
        _STATE["requested_end"] = end.isoformat()
        _STATE["seasons_total"] = len(seasons)
        initial.update(
            {
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
                "seasons_total": len(seasons),
            }
        )

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_run, args=(app, start, end), name="harmony-ingest", daemon=True
    )
    thread.start()
    return initial
