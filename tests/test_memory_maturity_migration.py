"""0047→0048 preserves originals; populated derived state prevents lossy downgrade."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "memory-maturity.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "0047")
    engine = create_engine(url)
    with engine.begin() as db:
        # Existing source rows and ciphertext-like payload remain byte-for-byte intact.
        db.execute(
            text(
                "INSERT INTO memory_learning_jobs (id,source_message_id,"
                "source_message_revision,source_conversation_id,source_sha256,extractor_version,"
                "settings_revision,status,error,created) VALUES "
                "('old-job','message',1,'chat','synthetic-sha','v1',0,'failed','synthetic',0)"
            )
        )
        before = dict(db.execute(text("SELECT * FROM memory_learning_jobs")).mappings().one())
    engine.dispose()
    command.upgrade(Config("alembic.ini"), "0048")
    yield url, before


def test_additive_retry_column_keeps_all_existing_job_values_and_survives_restart(migrated):
    url, before = migrated
    engine = create_engine(url)
    with engine.connect() as db:
        after = dict(db.execute(text("SELECT * FROM memory_learning_jobs")).mappings().one())
        assert {key: after[key] for key in before} == before and after["attempts"] == 1
        assert "conversation_summary_segments" in inspect(db).get_table_names()
    engine.dispose()
    reopened = create_engine(url)
    with reopened.connect() as db:
        assert db.scalar(text("SELECT attempts FROM memory_learning_jobs")) == 1
    reopened.dispose()


def test_downgrade_refuses_retry_history_before_any_schema_loss(migrated):
    url, _ = migrated
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("UPDATE memory_learning_jobs SET attempts=2"))
    with pytest.raises(RuntimeError, match="preserve"):
        command.downgrade(Config("alembic.ini"), "0047")
    with engine.connect() as db:
        assert db.scalar(text("SELECT attempts FROM memory_learning_jobs")) == 2
        assert "conversation_summary_segments" in inspect(db).get_table_names()
    engine.dispose()


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PG required")
def test_real_postgres_additive_segments_and_retry_metadata_preserve_original_rows(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci allowed")
    engine = create_engine(url)
    schema = "memory_maturity_" + uuid4().hex
    with engine.begin() as db:
        db.execute(CreateSchema(schema))
    try:
        spec = importlib.util.spec_from_file_location(
            "memory_maturity", Path("migrations/versions/0048_memory_maturity.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with engine.begin() as db:
            db.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(db)))
            for table in ["conversations", "messages", "memory_learning_jobs"]:
                db.execute(
                    text(
                        "CREATE TABLE " + table + " (id varchar(36) PRIMARY KEY, "
                        "content text NOT NULL)"
                    )
                )
                db.execute(text("INSERT INTO " + table + " VALUES ('synthetic','PRESERVE')"))
            module.upgrade()
            assert db.scalar(text("SELECT attempts FROM memory_learning_jobs")) == 1
            assert db.scalar(text("SELECT content FROM memory_learning_jobs")) == "PRESERVE"
            db.execute(
                text(
                    "INSERT INTO conversation_summary_segments VALUES "
                    "('synthetic','synthetic',1,'sha','EXACT SYNTHETIC EXCERPT',0)"
                )
            )
            with pytest.raises(RuntimeError, match="preserve"):
                module.downgrade()
            assert (
                db.scalar(text("SELECT excerpt FROM conversation_summary_segments"))
                == "EXACT SYNTHETIC EXCERPT"
            )
    finally:
        with engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        engine.dispose()
