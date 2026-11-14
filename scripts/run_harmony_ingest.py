r"""Detached runner for the real IMERG Final ingestion via Harmony.

Launch (survives the calling shell):

    Start-Process -WindowStyle Hidden -FilePath ".\.venv\Scripts\python.exe" `
      -ArgumentList "scripts\run_harmony_ingest.py" `
      -RedirectStandardOutput data\harmony_ingest.log `
      -RedirectStandardError data\harmony_ingest.err.log

Progress is written to data\harmony_ingest_status.json on every poll.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from app.config import Config
from app.services import harmony_ingest


class RunnerConfig(Config):
    AUTO_TRAIN_MODEL = False  # retraining happens after ingestion


STATUS_FILE = Config.DATA_DIR / "harmony_ingest_status.json"


def _write_status(status: dict) -> None:
    STATUS_FILE.write_text(
        json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    args = parser.parse_args()

    app = create_app(RunnerConfig)
    with app.app_context():
        status = harmony_ingest.start_harmony_ingest(args.start, args.end)
    _write_status(status)
    print(f"started: seasons_total={status['seasons_total']}", flush=True)

    while True:
        time.sleep(15)
        with app.app_context():
            status = harmony_ingest.harmony_ingest_status()
        _write_status(status)
        if status["seasons_done"] and status["seasons_done"] % 1 == 0:
            print(
                f"progress: {status['seasons_done']}/{status['seasons_total']} "
                f"seasons, days_ingested={status['days_ingested']} "
                f"days_updated={status['days_updated']} "
                f"errors={len(status['errors'])}",
                flush=True,
            )
        if not status["running"]:
            break

    ok = status.get("error") is None and status.get("model_error") is None
    print(
        f"finished: model_version={status.get('model_version')} "
        f"model_error={status.get('model_error')} "
        f"error={status.get('error')}",
        flush=True,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
