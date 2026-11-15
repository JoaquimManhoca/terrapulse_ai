"""Incremental IMERG Early updates through NASA Harmony.

Unlike ``harmony_ingest`` (complete rainy seasons only), this module can fetch
any date range, including the current season. Harmony crops the data to the
Manica bbox on the server, so a month is around 1 MB instead of hundreds of
megabytes of global granules.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from harmony import BBox, Client, Collection, Request

from ..config import Config
from ..extensions import db
from ..models import DailyObservation
from .earthdata import collection_coverage, earthdata_client
from .ingest import SOURCE, IngestedDay, read_manica_days, upsert_observations

EARLY_COLLECTION_ID = "C2723754850-GES_DISC"
DEFAULT_CHUNK_DAYS = 31
DOWNLOAD_RETRIES = 3
JOB_TIMEOUT_SECONDS = 45 * 60
MAX_CONCURRENT_JOBS = 4
POLL_SECONDS = 10
SUBMIT_RETRIES = 2

PROTECTED_SOURCES = ("imerg_final_daily",)


@dataclass
class UpdateResult:
    requested_start: date | None = None
    requested_end: date | None = None
    days_requested: int = 0
    days_ingested: int = 0
    days_updated: int = 0
    days_skipped: int = 0
    jobs_submitted: int = 0
    jobs_completed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "requested_start": (
                self.requested_start.isoformat() if self.requested_start else None
            ),
            "requested_end": (
                self.requested_end.isoformat() if self.requested_end else None
            ),
            "days_requested": self.days_requested,
            "days_ingested": self.days_ingested,
            "days_updated": self.days_updated,
            "days_skipped": self.days_skipped,
            "jobs_submitted": self.jobs_submitted,
            "jobs_completed": self.jobs_completed,
            "errors": list(self.errors),
        }


def date_chunks(
    start: date, end: date, chunk_days: int = DEFAULT_CHUNK_DAYS
) -> list[tuple[date, date]]:
    """Split an inclusive date range into inclusive chunks."""
    if end < start:
        raise ValueError("end must be on or after start")
    if chunk_days < 1:
        raise ValueError("chunk_days must be at least 1")

    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days - 1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _request(
    start: date,
    end: date,
    collection_id: str = EARLY_COLLECTION_ID,
) -> Request:
    return Request(
        collection=Collection(id=collection_id),
        spatial=BBox(*Config.MANICA_BBOX),
        temporal={
            "start": datetime.combine(start, dtime.min),
            "stop": datetime.combine(end, dtime.max).replace(microsecond=0),
        },
        variables=["precipitation"],
        format="application/netcdf",
    )


def _download_days(client: Client, job_id: str) -> list[IngestedDay]:
    """Download a completed Harmony job and parse its daily rows."""
    rows_by_day: dict[date, IngestedDay] = {}
    with TemporaryDirectory(prefix=f"harmony-update-{job_id[:8]}-") as temp_dir:
        downloads = client.download_all(
            job_id, directory=temp_dir, overwrite=True
        )
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


def _protected_days(start: date, end: date) -> set[date]:
    rows = (
        db.session.query(DailyObservation.day)
        .filter(
            DailyObservation.day >= start,
            DailyObservation.day <= end,
            DailyObservation.source.in_(PROTECTED_SOURCES),
        )
        .all()
    )
    return {row[0] for row in rows}


def _download_with_retries(
    client: Client, job_id: str, result: UpdateResult
) -> list[IngestedDay]:
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            return _download_days(client, job_id)
        except Exception as exc:  # noqa: BLE001 - retry transient downloads
            last_error = exc
            if attempt < DOWNLOAD_RETRIES:
                result.errors.append(
                    f"job {job_id[:8]}: download attempt {attempt} failed, "
                    f"retrying: {exc}"
                )
                time.sleep(min(15 * attempt, 60))
    raise RuntimeError(
        f"download failed after {DOWNLOAD_RETRIES} attempts: {last_error}"
    )


def update_early(
    start: date,
    end: date,
    client: Client | None = None,
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    progress=None,
    poll_seconds: float = POLL_SECONDS,
) -> UpdateResult:
    """Fetch IMERG Early for ``start..end`` and upsert it into the database.

    Final IMERG observations inside the range are protected: Early values never
    overwrite them. The caller owns the Flask app context.
    """
    if end < start:
        raise ValueError("end must be on or after start")

    coverage = collection_coverage(EARLY_COLLECTION_ID)
    if coverage is not None:
        first_day, last_day = coverage
        start = max(start, first_day)
        end = min(end, last_day)
    if end < start:
        return UpdateResult(
            requested_start=start,
            requested_end=end,
            days_requested=0,
        )

    result = UpdateResult(
        requested_start=start,
        requested_end=end,
        days_requested=(end - start).days + 1,
    )
    chunks = date_chunks(start, end, chunk_days)
    protected = _protected_days(start, end)
    client = client or earthdata_client()

    queue: list[tuple[date, date, int]] = [
        (chunk_start, chunk_end, 1)
        for chunk_start, chunk_end in chunks
    ]
    active: dict[str, dict] = {}

    while queue or active:
        while queue and len(active) < MAX_CONCURRENT_JOBS:
            chunk_start, chunk_end, attempt = queue.pop(0)
            try:
                job_id = client.submit(_request(chunk_start, chunk_end))
                if isinstance(job_id, dict):
                    job_id = job_id.get("jobID")
                if not isinstance(job_id, str) or not job_id:
                    raise ValueError(f"unexpected submit response: {job_id!r}")
            except Exception as exc:  # noqa: BLE001 - retry submissions
                if attempt < SUBMIT_RETRIES:
                    result.errors.append(
                        f"{chunk_start}..{chunk_end}: submit attempt "
                        f"{attempt} failed, retrying: {exc}"
                    )
                    queue.append((chunk_start, chunk_end, attempt + 1))
                    time.sleep(5)
                else:
                    result.errors.append(
                        f"{chunk_start}..{chunk_end}: submit failed after "
                        f"{attempt} attempts: {exc}"
                    )
                continue
            result.jobs_submitted += 1
            active[job_id] = {
                "start": chunk_start,
                "end": chunk_end,
                "attempt": attempt,
                "submitted_at": time.monotonic(),
            }

        for job_id, entry in list(active.items()):
            try:
                status = client.status(job_id)
            except Exception:  # noqa: BLE001 - transient network error
                continue
            state = status.get("status")
            if state == "successful":
                active.pop(job_id)
                try:
                    days = _download_with_retries(client, job_id, result)
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(
                        f"{entry['start']}..{entry['end']}: {exc}"
                    )
                    continue

                days = [
                    item
                    for item in days
                    if entry["start"] <= item.day <= entry["end"]
                ]
                days = [item for item in days if item.day not in protected]
                if not days:
                    result.errors.append(
                        f"{entry['start']}..{entry['end']}: no days returned"
                    )
                    continue

                ingested, updated, skipped, _ = upsert_observations(
                    days, source=SOURCE
                )
                db.session.commit()
                result.days_ingested += ingested
                result.days_updated += updated
                result.days_skipped += skipped
                result.jobs_completed += 1
                if progress is not None:
                    progress(result)
            elif state in ("failed", "canceled"):
                active.pop(job_id)
                attempt = entry.get("attempt", 1)
                if attempt < SUBMIT_RETRIES:
                    queue.append((entry["start"], entry["end"], attempt + 1))
                else:
                    result.errors.append(
                        f"{entry['start']}..{entry['end']}: "
                        f"{status.get('message', state)}"
                    )
            elif (
                time.monotonic() - entry["submitted_at"]
                > JOB_TIMEOUT_SECONDS
            ):
                active.pop(job_id)
                result.errors.append(
                    f"{entry['start']}..{entry['end']}: Harmony job timed out"
                )
                try:
                    client.cancel(job_id)
                except Exception:  # noqa: BLE001
                    pass

        if queue or active:
            time.sleep(poll_seconds)

    return result
