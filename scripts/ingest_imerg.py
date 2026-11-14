r"""Ingest NASA IMERG Early Daily NetCDF files into the local database.

Usage:
    .\.venv\Scripts\python.exe scripts\ingest_imerg.py --dir download-data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.services.ingest import ingest_imerg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default=None,
        help="Directory with IMERG granules (default: download-data).",
    )
    parser.add_argument(
        "--pattern",
        default=None,
        help="Glob pattern (default: *.nc4).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the value, coverage and QC flag for every processed day.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        result = ingest_imerg(
            Path(args.dir) if args.dir else app.config["INGEST_DIR"],
            args.pattern or app.config["IMERG_PATTERN"],
        )

    print(
        f"Ingested {result.ingested}, updated {result.updated}, "
        f"skipped {result.skipped}, errors {len(result.errors)}."
    )
    if result.days:
        days = sorted(item.day for item in result.days)
        print(f"Coverage: {days[0]} to {days[-1]} ({len(days)} days).")
        flagged = [item for item in result.days if item.qc_flag != "imerg_bbox_mean"]
        if flagged:
            print(f"QC: {len(flagged)} day(s) with partial/missing coverage.")
        if args.verbose:
            for item in sorted(result.days, key=lambda value: value.day):
                print(
                    f"  {item.day} | {item.precip_mm} mm | "
                    f"{item.coverage_pct}% | {item.qc_flag} | {item.source_file}"
                )
    for error in result.errors[:10]:
        print(f"  - {error}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
