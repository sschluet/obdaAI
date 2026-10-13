"""Real optional-project migration preserves existing revision/run child rows."""

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


def verify(monkeypatch, connection):
    connection.execute(text("CREATE TABLE projects (id varchar(36) PRIMARY KEY)"))
    connection.execute(
        text(
            "CREATE TABLE use_cases (id varchar(36) PRIMARY KEY, "
            "project_id varchar(36) NOT NULL REFERENCES projects(id), revision integer NOT NULL)"
        )
    )
    connection.execute(text("CREATE INDEX ix_use_cases_project_id ON use_cases(project_id)"))
    connection.execute(
        text(
            "CREATE TABLE use_case_revisions (use_case_id varchar(36) REFERENCES use_cases(id), "
            "revision integer, spec text NOT NULL, sha256 varchar(64) NOT NULL, "
            "PRIMARY KEY(use_case_id, revision))"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE use_case_runs (id varchar(36) PRIMARY KEY, "
            "use_case_id varchar(36) REFERENCES use_cases(id), snapshot text NOT NULL)"
        )
    )
    connection.execute(text("INSERT INTO projects VALUES ('project')"))
    connection.execute(text("INSERT INTO use_cases VALUES ('case', 'project', 1)"))
    connection.execute(
        text(
            "INSERT INTO use_case_revisions VALUES "
            "('case', 1, 'original definition', 'original hash')"
        )
    )
    connection.execute(
        text("INSERT INTO use_case_runs VALUES ('run', 'case', 'original snapshot')")
    )
    spec = importlib.util.spec_from_file_location(
        "optional_case_migration", Path("migrations/versions/0038_optional_use_case_project.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    module.upgrade()
    assert connection.scalar(text("SELECT project_id FROM use_cases")) == "project"
    assert connection.scalar(text("SELECT spec FROM use_case_revisions")) == "original definition"
    assert connection.scalar(text("SELECT snapshot FROM use_case_runs")) == "original snapshot"
    assert next(
        c for c in inspect(connection).get_columns("use_cases") if c["name"] == "project_id"
    )["nullable"]
    assert inspect(connection).get_foreign_keys("use_cases")[0]["referred_table"] == "projects"
    assert inspect(connection).get_indexes("use_cases")[0]["column_names"] == ["project_id"]
    connection.execute(text("INSERT INTO use_cases VALUES ('standalone', NULL, 1)"))
    with pytest.raises(RuntimeError, match="Associate standalone"):
        module.downgrade()
    assert connection.scalar(text("SELECT count(*) FROM use_cases")) == 2
    connection.execute(text("UPDATE use_cases SET project_id='project' WHERE id='standalone'"))
    module.downgrade()
    assert not next(
        c for c in inspect(connection).get_columns("use_cases") if c["name"] == "project_id"
    )["nullable"]
    assert connection.scalar(text("SELECT snapshot FROM use_case_runs")) == "original snapshot"
    if connection.dialect.name == "sqlite":
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []


def test_optional_case_migration_sqlite_real_child_references(monkeypatch):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        verify(monkeypatch, connection)
    # Commit must also succeed; a successful batch with deferred counters is insufficient.
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM use_cases")) == 2
        assert connection.scalar(text("SELECT snapshot FROM use_case_runs")) == "original snapshot"
    engine.dispose()


@pytest.mark.skipif(
    not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PostgreSQL required"
)
def test_optional_case_migration_postgres_real_child_references(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci allowed")
    engine = create_engine(url)
    schema = "optional_cases_" + uuid4().hex
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
