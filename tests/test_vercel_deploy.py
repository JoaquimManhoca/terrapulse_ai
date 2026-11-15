from __future__ import annotations

import json
from contextlib import nullcontext

import pytest

from app import create_app
from app.config import Config, _database_uri, _engine_options
from app.extensions import db
from build_vercel import build_public_assets, train_model_for_vercel


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
    vercel = _engine_options(uri, is_vercel=True)
    assert vercel["connect_args"] == {"prepare_threshold": None}
    assert vercel["pool_pre_ping"] is True
    assert vercel["pool_recycle"] == 300
    assert vercel["pool_size"] == 2
    assert vercel["max_overflow"] == 3
    assert "poolclass" not in vercel

    local = _engine_options(uri, is_vercel=False)
    assert local["pool_size"] == 5
    assert local["max_overflow"] == 5
    assert "poolclass" not in local


def test_supabase_direct_url_forces_ssl(monkeypatch):
    monkeypatch.delenv("SUPABASE_POOLER_HOST", raising=False)

    uri = _database_uri(
        "postgresql://postgres:secret@db.abcdefgh.supabase.co:5432/postgres"
    )

    assert uri == (
        "postgresql+psycopg://postgres:secret@db.abcdefgh.supabase.co:5432"
        "/postgres?sslmode=require"
    )


def test_supabase_direct_url_can_be_rewritten_to_ipv4_pooler(monkeypatch):
    monkeypatch.setenv(
        "SUPABASE_POOLER_HOST", "aws-1-eu-north-1.pooler.supabase.com"
    )
    monkeypatch.delenv("SUPABASE_POOLER_PORT", raising=False)

    uri = _database_uri(
        "postgres://postgres:secret@db.abcdefgh.supabase.co:5432/postgres"
    )

    assert uri == (
        "postgresql+psycopg://postgres.abcdefgh:secret@"
        "aws-1-eu-north-1.pooler.supabase.com:6543/postgres?sslmode=require"
    )


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


def test_vercel_function_explicitly_bundles_the_model():
    config = json.loads((Config.DATA_DIR.parent / "vercel.json").read_text())

    assert (
        config["functions"]["index.py"]["includeFiles"]
        == "data/models/onset_rf.joblib"
    )


def test_vercel_build_retrains_model_from_database(monkeypatch, capsys):
    import app
    from app.services import training

    class BuildApp:
        def app_context(self):
            return nullcontext()

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TRAIN_MODEL_AT_BUILD", "true")
    monkeypatch.setattr(app, "create_app", lambda: BuildApp())
    monkeypatch.setattr(
        training,
        "train_and_persist",
        lambda: {
            "version": "onset-rf-v1",
            "data_status": "real",
            "splits": {
                "train": {"rows": 60},
                "validation": {"rows": 20},
                "test": {"rows": 20},
            },
        },
    )

    train_model_for_vercel()

    assert "Trained onset-rf-v1 from 100 complete-season examples." in capsys.readouterr().out


def test_vercel_build_can_disable_retraining_and_uses_real_model(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TRAIN_MODEL_AT_BUILD", "false")

    train_model_for_vercel()


def test_vercel_build_uses_committed_model_by_default(monkeypatch):
    import app

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("TRAIN_MODEL_AT_BUILD", raising=False)
    monkeypatch.setattr(
        app,
        "create_app",
        lambda: pytest.fail("Default Vercel build must not retrain the model."),
    )

    train_model_for_vercel()
