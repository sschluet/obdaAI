"""Actual 0032 event-reference migration and downgrade loss prevention."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


def migration(monkeypatch, connection):
    spec = importlib.util.spec_from_file_location(
        "cleanup_migration", Path("migrations/versions/0032_deletion_cleanup.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    return module


def verify(monkeypatch, connection):
    connection.execute(text("CREATE TABLE source_ready_events (id integer PRIMARY KEY)"))
    connection.execute(
        text(
            "CREATE TABLE task_event_occurrences (id varchar(36) PRIMARY KEY, "
            "event_id integer NOT NULL REFERENCES source_ready_events(id), "
            "status varchar(20) NOT NULL)"
        )
    )
    connection.execute(text("INSERT INTO source_ready_events VALUES (1)"))
    connection.execute(text("INSERT INTO task_event_occurrences VALUES ('owned', 1, 'finished')"))
    module = migration(monkeypatch, connection)
    module.upgrade()
    assert connection.scalar(text("SELECT event_id FROM task_event_occurrences")) == 1
    assert (
        connection.scalar(text("SELECT deleted_event_snapshot FROM task_event_occurrences")) == ""
    )
    assert (
        inspect(connection).get_foreign_keys("task_event_occurrences")[0]["options"]["ondelete"]
        == "SET NULL"
    )
    connection.execute(
        text(
            "INSERT INTO deletion_cleanup "
            "(id, manifest, status, error, source_done, artifact_done, created) "
            "VALUES (:id, '[]', 'pending', '', :done, :done, 0)"
        ),
        {"id": "pending", "done": False},
    )
    with pytest.raises(RuntimeError, match="Finish deletion cleanup"):
        module.downgrade()
    connection.execute(text("DELETE FROM deletion_cleanup"))
    snapshot = '{"id":1,"source_sha256":"synthetic"}'
    connection.execute(
        text("UPDATE task_event_occurrences SET deleted_event_snapshot=:snapshot"),
        {"snapshot": snapshot},
    )
    connection.execute(text("DELETE FROM source_ready_events WHERE id=1"))
    assert connection.scalar(text("SELECT event_id FROM task_event_occurrences")) is None
    assert (
        connection.scalar(text("SELECT deleted_event_snapshot FROM task_event_occurrences"))
        == snapshot
    )
    assert connection.scalar(text("SELECT status FROM task_event_occurrences")) == "finished"
    with pytest.raises(RuntimeError, match="Preserve detached"):
        module.downgrade()
    assert "deletion_cleanup" in inspect(connection).get_table_names()
    connection.execute(text("DELETE FROM task_event_occurrences"))
    module.downgrade()
    assert "deletion_cleanup" not in inspect(connection).get_table_names()
    event_column = next(
        c
        for c in inspect(connection).get_columns("task_event_occurrences")
        if c["name"] == "event_id"
    )
    assert not event_column["nullable"]
    assert "deleted_event_snapshot" not in {
        c["name"] for c in inspect(connection).get_columns("task_event_occurrences")
    }


def test_cleanup_migration_sqlite_preserves_history(monkeypatch):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        verify(monkeypatch, connection)
    engine.dispose()


@pytest.mark.skipif(
    not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PostgreSQL required"
)
def test_cleanup_migration_postgres_preserves_history(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci allowed")
    engine = create_engine(url)
    schema = "cleanup_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            verify(monkeypatch, connection)
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
