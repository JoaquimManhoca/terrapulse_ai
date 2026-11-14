from __future__ import annotations

import pytest

from app import create_app
from app.config import Config, _database_uri, _engine_options
from app.extensions import db
from build_vercel import build_public_assets


def test_vercel_rejects_ephemeral_sqlite():
    class VercelSQLiteConfig(Config):
        IS_VERCEL = True
        SECRET_KEY = "configured-test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///vercel.db"

    with pytest.raises(RuntimeError, match="requires DATABASE_URL"):
        create_app(VercelSQLiteConfig)


def test_postgres_urls_use_psycopg_and_disable_prepared_statements():
    uri = _database_uri("postgresql://user:pass@host/db?sslmode=require")

    assert uri == "postgresql+psycopg://user:pass@host/db?sslmode=require"
    assert _engine_options(uri, is_vercel=True) == {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": {"prepare_threshold": None},
        "pool_size": 1,
        "max_overflow": 0,
    }


def test_sqlite_app_uses_sqlite_compatible_engine_options(tmp_path):
    class SQLiteConfig(Config):
        IS_VERCEL = False
        SQLALCHEMY_DATABASE_URI = (
            "sqlite:///" + (tmp_path / "app.db").as_posix()
        )
        RAW_DIR = tmp_path / "raw"
        INTERIM_DIR = tmp_path / "interim"
        PROCESSED_DIR = tmp_path / "processed"
        MODELS_DIR = tmp_path / "models"
        AUTO_TRAIN_MODEL = False

    app = create_app(SQLiteConfig)

    with app.app_context():
        assert db.engine.dialect.name == "sqlite"
        assert "connect_args" not in app.config["SQLALCHEMY_ENGINE_OPTIONS"]
        db.engine.dispose()


def test_vercel_app_omits_local_admin_routes(monkeypatch):
    class VercelPostgresConfig(Config):
        IS_VERCEL = True
        SECRET_KEY = "configured-test-secret-with-at-least-32-characters"
        SQLALCHEMY_DATABASE_URI = (
            "postgresql+psycopg://user:password@localhost/test"
        )
        AUTO_TRAIN_MODEL = False

    monkeypatch.setattr(db, "init_app", lambda app: None)
    monkeypatch.setattr(db, "create_all", lambda: None)
    app = create_app(VercelPostgresConfig)

    paths = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/health" in paths
    assert "/api/admin/train" not in paths
    assert "/api/admin/ingest-harmony" not in paths


def test_vercel_static_build_copies_public_assets(tmp_path):
    output = tmp_path / "public"

    build_public_assets(output)

    assert (output / "static" / "css" / "app.css").is_file()
    assert (output / "static" / "manifest.webmanifest").is_file()
    assert (output / "service-worker.js").is_file()
