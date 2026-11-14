"""Copy Flask's static assets to Vercel's public directory."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "app" / "static"


def build_public_assets(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        STATIC_DIR,
        destination / "static",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("service-worker.js"),
    )
    shutil.copy2(STATIC_DIR / "service-worker.js", destination / "service-worker.js")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "public")
    arguments = parser.parse_args()
    build_public_assets(arguments.output)
