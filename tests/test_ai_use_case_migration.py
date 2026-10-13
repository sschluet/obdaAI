"""0039 preserves legacy snapshots on actual SQLite and disposable PostgreSQL."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


def migration(monkeypatch, connection):
    spec = importlib.util.spec_from_file_location(
        "ai_use_case_migration", Path("migrations/versions/0039_ai_use_cases.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    return module


def baseline(connection):
    connection.execute(text("CREATE TABLE conversations (id varchar(36) PRIMARY KEY)"))
    connection.execute(text("CREATE TABLE runs (id varchar(36) PRIMARY KEY)"))
    connection.execute(text("CREATE TABLE use_cases (id varchar(36) PRIMARY KEY)"))
    connection.execute(
        text("CREATE TABLE use_case_runs (id varchar(36) PRIMARY KEY, snapshot text NOT NULL)")
    )
    connection.execute(text("INSERT INTO conversations VALUES ('old-chat')"))
    connection.execute(
        text("INSERT INTO use_case_runs VALUES ('old-result', 'ORIGINAL IMMUTABLE SNAPSHOT')")
    )


def verify(connection, module):
    module.upgrade()
    assert (
        connection.scalar(text("SELECT snapshot FROM use_case_runs WHERE id='old-result'"))
        == "ORIGINAL IMMUTABLE SNAPSHOT"
    )
    assert (
        connection.scalar(text("SELECT purpose FROM conversations WHERE id='old-chat'")) == "chat"
    )
    assert (
        connection.scalar(text("SELECT execution_run_id FROM use_case_runs WHERE id='old-result'"))
        is None
    )
    assert "use_case_dialogue_turns" in inspect(connection).get_table_names()
    module.downgrade()
    assert (
        connection.scalar(text("SELECT snapshot FROM use_case_runs WHERE id='old-result'"))
        == "ORIGINAL IMMUTABLE SNAPSHOT"
    )


def test_ai_migration_preserves_legacy_sqlite(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "legacy.sqlite"))
    with engine.begin() as connection:
        baseline(connection)
        verify(connection, migration(monkeypatch, connection))
    engine.dispose()


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PG required")
def test_ai_migration_actual_postgres(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci is allowed")
    engine = create_engine(url)
    schema = "ai_use_case_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            baseline(connection)
            verify(connection, migration(monkeypatch, connection))
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


@pytest.mark.parametrize("kind", ["definition", "conversation"])
def test_ai_migration_refuses_lossy_downgrade(tmp_path, monkeypatch, kind):
    engine = create_engine("sqlite:///" + str(tmp_path / "future.sqlite"))
    with engine.begin() as connection:
        baseline(connection)
        module = migration(monkeypatch, connection)
        module.upgrade()
        if kind == "definition":
            connection.execute(text("CREATE TABLE use_case_revisions (spec text NOT NULL)"))
            connection.execute(
                text("INSERT INTO use_case_revisions VALUES (:spec)"),
                {"spec": '{"execution_kind":"ai","processing_prompt":"Synthetic"}'},
            )
        else:
            connection.execute(text("UPDATE conversations SET purpose='use_case'"))
        with pytest.raises(RuntimeError, match="Preserve AI use-case"):
            module.downgrade()
        assert "use_case_uploads" in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT snapshot FROM use_case_runs")) == (
            "ORIGINAL IMMUTABLE SNAPSHOT"
        )
    engine.dispose()
