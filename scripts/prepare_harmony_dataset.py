"""Download NASA IMERG Final data through Harmony and create temporal splits.

Run:
    .\\.venv\\Scripts\\python.exe scripts\\prepare_harmony_dataset.py
"""

from __future__ import annotations

import argparse
import json
import netrc
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from harmony import BBox, Client, Collection, Request

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.config import Config
from app.ml.training_data import (
    FEATURE_COLUMNS,
    PREDICTION_HORIZON_DAYS,
    TARGET_COLUMN,
    build_onset_dataset,
    split_by_season,
)
from app.services.ingest import read_manica_days

COLLECTION_ID = "C2723754864-GES_DISC"
COLLECTION_SHORT_NAME = "GPM_3IMERGDF"
DEFAULT_START = date(1998, 9, 2)
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "processed" / "harmony_onset"


def _earthdata_client() -> Client:
    token = os.environ.get("EARTHDATA_TOKEN")
    if token:
        return Client(token=token)

    netrc_path = os.environ.get("EARTHDATA_NETRC")
    try:
        credentials = netrc.netrc(netrc_path or None).authenticators(
            "urs.earthdata.nasa.gov"
        )
    except (FileNotFoundError, netrc.NetrcParseError, OSError):
        credentials = None

    if credentials and credentials[0] and credentials[2]:
        return Client(auth=(credentials[0], credentials[2]))

    raise RuntimeError(
        "Earthdata Login is not configured. Set EARTHDATA_TOKEN, or add an "
        "Earthdata entry for urs.earthdata.nasa.gov in %USERPROFILE%\\.netrc. "
        "If the file is elsewhere, set EARTHDATA_NETRC to its path. "
        "Never put credentials in source code."
    )


def _complete_seasons(start: date, end: date) -> list[tuple[int, date, date]]:
    seasons = []
    for year in range(start.year, end.year + 1):
        season_start = date(year, 10, 1)
        season_end = date(year + 1, 3, 31)
        request_start = season_start - timedelta(days=29)
        request_end = season_end + timedelta(days=Config.ONSET_HORIZON_DAYS)
        if request_start >= start and request_end <= end:
            seasons.append((year, request_start, request_end))
    return seasons


def _download_season(
    client: Client,
    season_year: int,
    start: date,
    end: date,
) -> list[dict]:
    request = Request(
        collection=Collection(id=COLLECTION_ID),
        spatial=BBox(*Config.MANICA_BBOX),
        temporal={
            "start": datetime.combine(start, time.min),
            "stop": datetime.combine(end, time.max).replace(microsecond=0),
        },
        variables=["precipitation"],
        format="application/netcdf",
    )
    if not request.is_valid():
        raise ValueError(f"Harmony rejected the request for season {season_year}.")

    rows_by_day: dict[date, dict] = {}
    with TemporaryDirectory(prefix=f"imerg-{season_year}-") as temp_dir:
        job_id = client.submit(request)
        downloads = client.download_all(
            job_id,
            directory=temp_dir,
            overwrite=True,
        )
        files = [Path(download.result()) for download in downloads]
        if not files:
            raise RuntimeError(
                f"Harmony returned no files for season {season_year}."
            )

        for path in files:
            for observation in read_manica_days(path):
                row = {
                    "day": observation.day,
                    "precip_mm": observation.precip_mm,
                    "coverage_pct": observation.coverage_pct,
                }
                previous = rows_by_day.get(observation.day)
                if previous is not None and previous != row:
                    raise ValueError(
                        f"Conflicting Harmony values for {observation.day}."
                    )
                rows_by_day[observation.day] = row

    rows = list(rows_by_day.values())
    if not rows:
        raise RuntimeError(
            f"Harmony files contained no daily precipitation for season "
            f"{season_year}."
        )
    print(
        f"Season {season_year}-{season_year + 1}: "
        f"{len(rows)} daily observations downloaded."
    )
    return rows


def _write_splits(
    splits: dict[str, pd.DataFrame],
    output_dir: Path,
    start: date,
    end: date,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    split_manifest = {}
    for name, frame in splits.items():
        frame.to_csv(output_dir / f"{name}.csv", index=False)
        split_manifest[name] = {
            "rows": len(frame),
            "seasons": sorted(
                int(year) for year in frame["season_year"].unique()
            ),
            "positive_labels": int(frame[TARGET_COLUMN].sum()),
            "negative_labels": int((frame[TARGET_COLUMN] == 0).sum()),
        }

    manifest = {
        "collection_id": COLLECTION_ID,
        "short_name": COLLECTION_SHORT_NAME,
        "version": "07",
        "data_source": "NASA GPM IMERG Final Daily via Earthdata Harmony",
        "bbox": list(Config.MANICA_BBOX),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "target": (
            "Effective onset, generated by the configured rainfall rule, "
            f"within the next {PREDICTION_HORIZON_DAYS} days."
        ),
        "features": list(FEATURE_COLUMNS),
        "split_method": "chronological by rainy season; no season is shared",
        "splits": split_manifest,
        "warning": (
            "Labels are weak labels derived from rainfall rules, not observed "
            "maize planting success or yield."
        ),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=DEFAULT_START,
        help="Earliest date to request (default: 1998-09-02).",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=date.today() - timedelta(days=120),
        help="Latest date to request (default: 120 days ago for Final data).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for train.csv, validation.csv, test.csv and manifest.",
    )
    args = parser.parse_args()

    if args.end_date < args.start_date:
        parser.error("--end-date must be on or after --start-date.")

    seasons = _complete_seasons(args.start_date, args.end_date)
    if not seasons:
        parser.error(
            "The requested dates do not contain a complete rainy season plus "
            "the required feature and onset-verification windows."
        )

    try:
        client = _earthdata_client()
    except RuntimeError as exc:
        parser.error(str(exc))

    observations = []
    for season_year, request_start, request_end in seasons:
        observations.extend(
            _download_season(
                client,
                season_year,
                request_start,
                request_end,
            )
        )

    frame = pd.DataFrame(observations).drop_duplicates("day", keep="last")
    examples = build_onset_dataset(frame)
    splits = split_by_season(examples)
    _write_splits(splits, args.output_dir, args.start_date, args.end_date)

    print(f"Dataset rows: {len(examples)}")
    print(f"Train/validation/test files written to: {args.output_dir}")
    print("Labels are rainfall-rule proxies, not observed crop outcomes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
