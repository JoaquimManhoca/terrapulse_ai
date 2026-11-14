"""Ingest NASA IMERG Early Daily (3B-DAY-E) NetCDF files into SQLite.

The loader reads the Manica bounding box from each granule, stores the mean
daily precipitation of the valid cells, and records how much of the box was
covered. It is idempotent: running it again refreshes the same days.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import xarray as xr

from ..config import Config
from ..extensions import db
from ..models import DailyObservation

SOURCE = "imerg_early_daily"
FINAL_SOURCE = "imerg_final_daily"
FILENAME_RE = re.compile(r"3B-DAY-E\..*?\.(\d{8})-S\d{6}-E\d{6}\.", re.IGNORECASE)
PRECIP_CANDIDATES = ("precipitation", "precipitationCal", "precip")
SUPPORTED_SUFFIXES = {".nc4", ".nc", ".h5", ".hdf5"}


@dataclass
class IngestedDay:
    day: date
    precip_mm: float | None
    coverage_pct: float
    qc_flag: str
    source_file: str


@dataclass
class IngestResult:
    ingested: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    days: list[IngestedDay] = field(default_factory=list)

    def as_dict(self) -> dict:
        days = sorted(item.day for item in self.days)
        return {
            "ingested": self.ingested,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "days": len(days),
            "partial_days": sum(
                1 for item in self.days if item.qc_flag == "imerg_partial"
            ),
            "missing_days": sum(
                1 for item in self.days if item.qc_flag == "imerg_missing"
            ),
            "first_day": days[0].isoformat() if days else None,
            "last_day": days[-1].isoformat() if days else None,
        }


def discover_files(directory: Path | str, pattern: str = "*.nc4") -> list[Path]:
    root = Path(directory)
    if not root.exists():
        raise FileNotFoundError(f"IMERG directory not found: {root}")
    files = [
        path
        for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    # Prefer the original download over "name (1).nc4" duplicates.
    return sorted(files, key=lambda path: ("(1)" in path.name, path.name))


def _date_from_value(value) -> date | None:
    if value is None:
        return None
    try:
        if isinstance(value, np.datetime64):
            return value.astype("datetime64[D]").astype(object)
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _date_from_attrs_or_name(path: Path, ds: xr.Dataset | None) -> date | None:
    if ds is not None:
        begin = ds.attrs.get("BeginDate")
        if begin:
            parsed = _date_from_value(begin)
            if parsed is not None:
                return parsed
        if "time" in ds and ds["time"].size:
            parsed = _date_from_value(np.atleast_1d(ds["time"].values)[0])
            if parsed is not None:
                return parsed

    match = FILENAME_RE.search(path.name)
    if match:
        raw = match.group(1)
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    return None


def _precipitation_name(ds: xr.Dataset) -> str:
    for candidate in PRECIP_CANDIDATES:
        if candidate in ds:
            return candidate
    for name, variable in ds.variables.items():
        units = str(variable.attrs.get("units", "")).lower()
        if "mm" in units and variable.ndim >= 2:
            return name
    raise KeyError("no precipitation variable found")


def _bbox_values(
    ds: xr.Dataset,
    variable_name: str,
    time_index: int | None = None,
) -> np.ndarray:
    lat_name = "lat" if "lat" in ds.coords else "latitude"
    lon_name = "lon" if "lon" in ds.coords else "longitude"
    lon_min, lat_min, lon_max, lat_max = Config.MANICA_BBOX

    lon_values = np.asarray(ds[lon_name].values)
    lat_values = np.asarray(ds[lat_name].values)
    lon_index = np.where((lon_values >= lon_min) & (lon_values <= lon_max))[0]
    lat_index = np.where((lat_values >= lat_min) & (lat_values <= lat_max))[0]
    if lon_index.size == 0 or lat_index.size == 0:
        raise ValueError("Manica bbox does not intersect the granule grid")

    indexers = {lon_name: lon_index, lat_name: lat_index}
    time_name = "time" if "time" in ds[variable_name].dims else None
    if time_index is not None:
        if time_name is None:
            raise ValueError("time index requested for a variable without time")
        indexers[time_name] = time_index

    subset = ds[variable_name].isel(indexers)
    values = np.asarray(subset.values, dtype=float).squeeze()
    if values.ndim == 3:
        values = values[0]
    if values.ndim != 2:
        raise ValueError(f"unexpected precipitation shape: {values.shape}")
    return values


def _summarize(day: date, values: np.ndarray, source_file: str) -> IngestedDay:
    total = int(values.size)
    valid = np.isfinite(values)
    valid_count = int(valid.sum())
    coverage = round(100.0 * valid_count / total, 1) if total else 0.0

    if valid_count:
        precip = round(float(np.nanmean(values)), 2)
        qc_flag = "imerg_bbox_mean" if valid_count == total else "imerg_partial"
    else:
        precip = None
        qc_flag = "imerg_missing"

    return IngestedDay(
        day=day,
        precip_mm=precip,
        coverage_pct=coverage,
        qc_flag=qc_flag,
        source_file=source_file,
    )


def read_manica_days(path: Path | str) -> list[IngestedDay]:
    file_path = Path(path)
    with xr.open_dataset(file_path) as ds:
        variable_name = _precipitation_name(ds)
        time_name = "time" if "time" in ds.coords else None

        if time_name is not None and ds[time_name].size:
            times = np.atleast_1d(ds[time_name].values)
            if times.size == 1:
                day = _date_from_value(times[0])
                if day is None:
                    day = _date_from_attrs_or_name(file_path, ds)
                if day is None:
                    raise ValueError(f"cannot determine the date of {file_path.name}")
                values = _bbox_values(ds, variable_name, 0)
                return [_summarize(day, values, file_path.name)]

            days: list[IngestedDay] = []
            for index, value in enumerate(times):
                day = _date_from_value(value)
                if day is None:
                    raise ValueError(
                        f"invalid time value {value!r} at index {index} "
                        f"in {file_path.name}"
                    )
                values = _bbox_values(ds, variable_name, index)
                days.append(_summarize(day, values, file_path.name))
            return days

        day = _date_from_attrs_or_name(file_path, ds)
        if day is None:
            raise ValueError(f"cannot determine the date of {file_path.name}")
        values = _bbox_values(ds, variable_name)
        return [_summarize(day, values, file_path.name)]


def read_manica_day(path: Path | str) -> IngestedDay:
    days = read_manica_days(path)
    if len(days) != 1:
        raise ValueError(
            f"expected exactly one day in {Path(path).name}, found {len(days)}"
        )
    return days[0]


def upsert_observations(
    days: list[IngestedDay],
    source: str = SOURCE,
) -> tuple[int, int, int, list[IngestedDay]]:
    """Insert or refresh daily observations from parsed IMERG days.

    Returns (ingested, updated, skipped, upserted) where ``upserted`` lists
    only the days that were actually written to the database. Rows are not
    committed; callers own the transaction.
    """
    ingested = updated = skipped = 0
    upserted: list[IngestedDay] = []
    for item in days:
        existing = (
            db.session.query(DailyObservation)
            .filter_by(day=item.day)
            .one_or_none()
        )
        if existing is None:
            db.session.add(
                DailyObservation(
                    day=item.day,
                    precip_mm=item.precip_mm,
                    coverage_pct=item.coverage_pct,
                    source=source,
                    qc_flag=item.qc_flag,
                )
            )
            ingested += 1
            upserted.append(item)
        else:
            existing.precip_mm = item.precip_mm
            existing.coverage_pct = item.coverage_pct
            existing.source = source
            existing.qc_flag = item.qc_flag
            updated += 1
            upserted.append(item)
    return ingested, updated, skipped, upserted


def ingest_imerg(
    directory: Path | str | None = None,
    pattern: str | None = None,
) -> IngestResult:
    root = Path(directory) if directory is not None else Config.INGEST_DIR
    glob_pattern = pattern or Config.IMERG_PATTERN
    result = IngestResult()
    seen: set[date] = set()
    unique_days: list[IngestedDay] = []

    for path in discover_files(root, glob_pattern):
        try:
            for ingested in read_manica_days(path):
                if ingested.day in seen:
                    result.skipped += 1
                    continue
                seen.add(ingested.day)
                unique_days.append(ingested)
        except Exception as exc:  # noqa: BLE001 - report and continue with the batch
            result.errors.append(f"{path.name}: {exc}")

    (
        result.ingested,
        result.updated,
        replace_skipped,
        result.days,
    ) = upsert_observations(unique_days)
    result.skipped += replace_skipped

    db.session.commit()
    return result
