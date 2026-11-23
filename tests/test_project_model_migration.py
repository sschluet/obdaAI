"""Additive 0049→0050 migration preserves records and refuses lossy downgrade."""

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
    url = "sqlite:///" + str(tmp_path / "project-model.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "0049")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO projects (id,name,description,instructions,label,revision,"
                        "archived,icon,kind) VALUES ('synthetic','Synthetic project',"
                        "'Synthetic original description','Keep synthetic instructions',"
                        "'LOCAL_ONLY',4,false,'folder','project')"))
        before = dict(db.execute(text("SELECT * FROM projects")).mappings().one())
    engine.dispose()
    command.upgrade(Config("alembic.ini"), "0050")
    return url, before


def test_additive_column_preserves_every_original_project_value_and_restarts(migrated):
    url, before = migrated
    for _ in range(2):
        engine = create_engine(url)
        with engine.connect() as db:
            after = dict(db.execute(text("SELECT * FROM projects")).mappings().one())
            assert {key: after[key] for key in before} == before
            assert after["model_policy"] == "{}"
        engine.dispose()


def test_downgrade_refuses_nondefault_model_preferences_without_losing_data(migrated, monkeypatch):
    url, _ = migrated
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("UPDATE projects SET model_policy=:policy"),
                   {"policy": '{"provider_id":"synthetic","model":"synthetic"}'})
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    with pytest.raises(RuntimeError, match="preferences"):
        command.downgrade(Config("alembic.ini"), "0049")
    with engine.connect() as db:
        assert db.scalar(text("SELECT model_policy FROM projects")) != "{}"
        assert (db.scalar(text("SELECT description FROM projects"))
                == "Synthetic original description")
    engine.dispose()


def test_empty_preference_downgrade_only_removes_additive_column(migrated, monkeypatch):
    url, before = migrated
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.downgrade(Config("alembic.ini"), "0049")
    engine = create_engine(url)
    with engine.connect() as db:
        assert "model_policy" not in {c["name"] for c in inspect(db).get_columns("projects")}
        assert dict(db.execute(text("SELECT * FROM projects")).mappings().one()) == before
    engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("HUB_CI_DATABASE_URL"), reason="Disposable PostgreSQL not set"
)
def test_real_postgres_model_policy_additive_preservation_and_downgrade_guard(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only isolated loopback hub_ci allowed")
    engine = create_engine(url)
    schema = "project_model_" + uuid4().hex
    with engine.begin() as db:
        db.execute(CreateSchema(schema))
    try:
        spec = importlib.util.spec_from_file_location(
            "project_model_migration", Path("migrations/versions/0050_project_model_policy.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with engine.begin() as db:
            db.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            db.execute(text(
                "CREATE TABLE projects (id text PRIMARY KEY, description text NOT NULL)"
            ))
            db.execute(text("INSERT INTO projects VALUES ('synthetic','PRESERVE ORIGINAL')"))
            monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(db)))
            module.upgrade()
            assert db.scalar(text("SELECT model_policy FROM projects")) == "{}"
            assert db.scalar(text("SELECT description FROM projects")) == "PRESERVE ORIGINAL"
            db.execute(text("UPDATE projects SET model_policy=:value"),
                       {"value": '{"provider_id":"synthetic","model":"synthetic"}'})
            with pytest.raises(RuntimeError, match="preferences"):
                module.downgrade()
            assert db.scalar(text("SELECT description FROM projects")) == "PRESERVE ORIGINAL"
    finally:
        with engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        engine.dispose()
