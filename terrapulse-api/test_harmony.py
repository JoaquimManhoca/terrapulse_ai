
"""Compatibility entry point for preparing NASA Harmony training splits."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from scripts.prepare_harmony_dataset import main


if __name__ == "__main__":
    raise SystemExit(main())
