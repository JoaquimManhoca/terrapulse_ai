"""Application configuration for TerraPulse AI."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from sqlalchemy.pool import NullPool

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

IS_VERCEL_DEPLOYMENT = os.getenv("VERCEL") == "1"

# Supabase only publishes IPv6 records for db.<ref>.supabase.co. Serverless
# platforms such as Vercel are IPv4-only, so direct connections fail there.
# Using the pooler host (IPv4) fixes it; see docs/DEPLOY_VERCEL.md.
_SUPABASE_DIRECT_HOST = re.compile(r"^db\.([a-z0-9]+)\.supabase\.co$")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_uri(value: str | None) -> str:
    if not value:
        return "sqlite:///" + (BASE_DIR / "data" / "terrapulse.db").as_posix()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if not value.startswith("postgresql://"):
        return value

    parts = urlsplit(value)
    host = parts.hostname or ""
    netloc = parts.netloc
    query = dict(parse_qsl(parts.query))

    pooler_host = os.getenv("SUPABASE_POOLER_HOST", "").strip()
    match = _SUPABASE_DIRECT_HOST.match(host)
    if match and pooler_host:
        project_ref = match.group(1)
        user = parts.username or "postgres"
        if not user.startswith("postgres."):
            user = f"postgres.{project_ref}"
        credentials = f"{user}:{parts.password}" if parts.password else user
        port = os.getenv("SUPABASE_POOLER_PORT", "6543").strip() or "6543"
        netloc = f"{credentials}@{pooler_host}:{port}"

    if "sslmode" not in query and (
        host.endswith(".supabase.co") or host.endswith(".supabase.com")
    ):
        query["sslmode"] = "require"

    return urlunsplit(
        ("postgresql+psycopg", netloc, parts.path, urlencode(query), parts.fragment)
    )


def _engine_options(database_uri: str, is_vercel: bool) -> dict:
    """Engine options tuned for a long-lived process or a serverless function."""
    options: dict = {}
    if database_uri.startswith("postgresql+psycopg://"):
        options["connect_args"] = {"prepare_threshold": None}
    if is_vercel:
        # Functions are short-lived and scale horizontally; a shared pool is
        # wasted and can exhaust connections (or time out under concurrency).
        options["poolclass"] = NullPool
    else:
        options["pool_pre_ping"] = True
        options["pool_recycle"] = 300
    return options


class Config:
    IS_VERCEL = IS_VERCEL_DEPLOYMENT
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    DATA_DIR = BASE_DIR / "data"
    RAW_DIR = DATA_DIR / "raw"
    INTERIM_DIR = DATA_DIR / "interim"
    PROCESSED_DIR = DATA_DIR / "processed"
    MODELS_DIR = DATA_DIR / "models"

    # Downloaded IMERG granules (kept out of git)
    INGEST_DIR = Path(os.getenv("IMERG_DIR", BASE_DIR / "download-data"))
    IMERG_PATTERN = os.getenv("IMERG_PATTERN", "*.nc4")

    SQLALCHEMY_DATABASE_URI = _database_uri(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = (
        {"poolclass": NullPool}
        if IS_VERCEL_DEPLOYMENT
        else {"pool_pre_ping": True, "pool_recycle": 300}
    )

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_VERCEL_DEPLOYMENT

    DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "pt")
    DEFAULT_REGION = os.getenv("DEFAULT_REGION", "manica")
    DEFAULT_CROP = os.getenv("DEFAULT_CROP", "milho")

    # Selectable locations and crops. Only combinations marked as supported
    # have a rainfall series and calibrated onset rules behind them.
    REGIONS = {
        "manica": {"label_key": "region.manica", "supported": True},
        "chimoio": {"label_key": "region.chimoio", "supported": False},
        "gondola": {"label_key": "region.gondola", "supported": False},
        "sussundenga": {"label_key": "region.sussundenga", "supported": False},
    }
    CROPS = {
        "milho": {"label_key": "crop.milho", "supported": True},
        "feijao": {"label_key": "crop.feijao", "supported": False},
        "mandioca": {"label_key": "crop.mandioca", "supported": False},
    }

    AUTO_TRAIN_MODEL = _as_bool(
        os.getenv("AUTO_TRAIN_MODEL"),
        default=not IS_VERCEL_DEPLOYMENT,
    )
    FORECAST_ENABLED = _as_bool(os.getenv("FORECAST_ENABLED"), default=True)

    # NASA Earthdata (Harmony ingestion). Never put credentials in source:
    # prefer EARTHDATA_TOKEN or a .netrc entry for urs.earthdata.nasa.gov.
    EARTHDATA_TOKEN = os.getenv("EARTHDATA_TOKEN")

    OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
    MANICA_LAT = float(os.getenv("MANICA_LAT", "-18.8937"))
    MANICA_LON = float(os.getenv("MANICA_LON", "32.9252"))
    MANICA_BBOX = (
        float(os.getenv("MANICA_LON_MIN", "32.69834")),
        float(os.getenv("MANICA_LAT_MIN", "-19.13725")),
        float(os.getenv("MANICA_LON_MAX", "33.17879")),
        float(os.getenv("MANICA_LAT_MAX", "-18.70926")),
    )

    # Agronomic / onset rules (configurable, defaults documented in docs/METODOLOGIA.md)
    DECISION_DRY_DAY_MM = float(os.getenv("DECISION_DRY_DAY_MM", "1.0"))
    ONSET_WINDOW_DAYS = int(os.getenv("ONSET_WINDOW_DAYS", "3"))
    ONSET_THRESHOLD_MM = float(os.getenv("ONSET_THRESHOLD_MM", "20.0"))
    ONSET_DRY_SPELL_DAYS = int(os.getenv("ONSET_DRY_SPELL_DAYS", "7"))
    ONSET_HORIZON_DAYS = int(os.getenv("ONSET_HORIZON_DAYS", "21"))
    SEASON_START_MONTH = int(os.getenv("SEASON_START_MONTH", "10"))
    SEASON_START_DAY = int(os.getenv("SEASON_START_DAY", "1"))
