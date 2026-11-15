"""Copy Flask's static assets to Vercel's public directory."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "app" / "static"
load_dotenv(ROOT / ".env")


def build_public_assets(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        STATIC_DIR,
        destination / "static",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("service-worker.js"),
    )
    shutil.copy2(STATIC_DIR / "service-worker.js", destination / "service-worker.js")


def train_model_for_vercel() -> None:
    if os.environ.get("VERCEL") != "1":
        return

    train_at_build = os.environ.get("TRAIN_MODEL_AT_BUILD", "false").strip().lower()
    if train_at_build in {"0", "false", "no", "off"}:
        train_enabled = False
    else:
        train_enabled = True

    if train_enabled:
        from app import create_app
        from app.services.training import train_and_persist

        app = create_app()
        with app.app_context():
            metadata = train_and_persist()
        if metadata.get("data_status") != "real":
            raise RuntimeError(
                "Vercel build did not produce a model from real IMERG data."
            )
        split_rows = sum(
            split.get("rows", 0)
            for split in metadata.get("splits", {}).values()
        )
        print(
            f"Trained {metadata['version']} from {split_rows} "
            "complete-season examples."
        )

    from app.ml.persistence import load_active_model

    model = load_active_model(ROOT / "data" / "models")
    if model is None or model[1].get("data_status") != "real":
        raise RuntimeError(
            "No valid real-data model is available for the Vercel Function."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "public")
    arguments = parser.parse_args()
    train_model_for_vercel()
    build_public_assets(arguments.output)
