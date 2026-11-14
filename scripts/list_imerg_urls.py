r"""Write the GES DISC URLs for a date range to a text file.

Examples:
    .\.venv\Scripts\python.exe scripts\list_imerg_urls.py --start 2023-10-01 --end 2026-11-12 --out urls.txt
    .\.venv\Scripts\python.exe scripts\list_imerg_urls.py --start 2023-10-01 --end 2026-11-12 --seasons-only
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.imerg_urls import IMERG_BASE_URL, imerg_urls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=date(2023, 10, 1),
        help="First day (YYYY-MM-DD). Default: 2023-10-01.",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=date.today(),
        help="Last day (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output file. Default: print to stdout.",
    )
    parser.add_argument(
        "--base-url",
        default=IMERG_BASE_URL,
        help="GES DISC product base URL.",
    )
    parser.add_argument(
        "--seasons-only",
        action="store_true",
        help="Keep only October-March days.",
    )
    args = parser.parse_args()

    urls = imerg_urls(args.start, args.end, args.base_url, args.seasons_only)
    text = "\n".join(urls) + ("\n" if urls else "")

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote {len(urls)} URLs to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
