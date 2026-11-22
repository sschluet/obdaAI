"""Additive Drive migration preserves existing private state and blocks lossy downgrade."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from hub.db import Memory, PersonalProfile
from hub.google_drive_files import GoogleDriveTransfer
from hub.google_drive_setup import GoogleDriveOAuthAttempt
from hub.integrations import Integration
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

TABLES = ("memories", "memory_revisions", "personal_profile", "integrations")


def snapshot(connection):
    return {
        table: [dict(row) for row in connection.execute(text("SELECT * FROM " + table)).mappings()]
        for table in TABLES
    }


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "drive-migration.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "0046")
    engine = create_engine(url)
    with Session(engine) as db:
        profile = db.get(PersonalProfile, 1)
        profile.revision = 9
        profile.enabled = True
        profile.fields = '{"name":"Synthetic old profile"}'
        db.add(
            Memory(
                id="synthetic-vault",
                storage="vault",
                path="AI/Memory/preserved.md",
                content="Original synthetic Vault",
                sha256="a" * 64,
            )
        )
        db.add(
            Memory(
                id="synthetic-native",
                storage="app",
                path="app-memory/preserved",
                content="Original synthetic native memory",
                sha256="b" * 64,
            )
        )
        db.add(
            Integration(
                id="synthetic-old-integration",
                name="Synthetic old connection",
                kind="gmail",
                config="{}",
                encrypted_secret="PRESERVE_ENCRYPTED_VALUE",
                revision=7,
                enabled=False,
            )
        )
        db.commit()
    with engine.connect() as connection:
        before = snapshot(connection)
    engine.dispose()
    command.upgrade(Config("alembic.ini"), "0047")
    yield url, before


def test_drive_upgrade_preserves_existing_profile_vault_native_and_credentials(migrated):
    url, before = migrated
    engine = create_engine(url)
    with engine.connect() as connection:
        assert snapshot(connection) == before
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0047"
        assert {"google_drive_oauth_attempts", "google_drive_transfers"} <= set(
            inspect(connection).get_table_names()
        )
    engine.dispose()
    reopened = create_engine(url)
    with reopened.connect() as connection:
        assert snapshot(connection) == before
    reopened.dispose()


@pytest.mark.parametrize("blocker", ["oauth", "transfer", "profile"])
def test_downgrade_refuses_oauth_upload_audit_or_drive_configuration(migrated, blocker):
    url, before = migrated
    engine = create_engine(url)
    with Session(engine) as db:
        if blocker == "oauth":
            db.add(
                GoogleDriveOAuthAttempt(
                    request_id=str(uuid4()),
                    request_digest="a" * 64,
                    operation="oauth",
                    integration_id="synthetic",
                    profile_revision=1,
                    session_hash="b" * 64,
                    status="uncertain",
                    expires=1,
                )
            )
        elif blocker == "transfer":
            db.add(
                GoogleDriveTransfer(
                    request_id=str(uuid4()),
                    request_digest="a" * 64,
                    integration_id="synthetic",
                    profile_revision=1,
                    operation="export",
                    status="uncertain",
                )
            )
        else:
            db.add(
                Integration(name="Synthetic Drive", kind="google_drive", config="{}", enabled=False)
            )
        db.commit()
    engine.dispose()
    with pytest.raises(RuntimeError, match="Preserve"):
        command.downgrade(Config("alembic.ini"), "0046")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0047"
        assert "google_drive_transfers" in inspect(connection).get_table_names()
        for table in ("memories", "memory_revisions", "personal_profile"):
            assert snapshot(connection)[table] == before[table]
    engine.dispose()


def test_empty_drive_state_downgrade_retains_prior_native_memory(migrated):
    url, before = migrated
    command.downgrade(Config("alembic.ini"), "0046")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert snapshot(connection) == before
        assert "google_drive_transfers" not in inspect(connection).get_table_names()
    engine.dispose()


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PG required")
def test_drive_additive_actual_postgres_preserves_all_original_rows(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci allowed")
    engine = create_engine(url)
    schema = "drive_migration_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        spec = importlib.util.spec_from_file_location(
            "drive_migration", Path("migrations/versions/0047_google_drive.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
            for table in TABLES:
                connection.execute(
                    text(
                        "CREATE TABLE " + table + " (id text PRIMARY KEY, content text, kind text)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO "
                        + table
                        + " VALUES ('synthetic','PRESERVE EXACT SYNTHETIC CONTENT','existing')"
                    )
                )
            before = snapshot(connection)
            module.upgrade()
            assert snapshot(connection) == before
            assert "google_drive_oauth_attempts" in inspect(connection).get_table_names()
            connection.execute(
                text("INSERT INTO integrations VALUES ('drive','PRESERVE CONFIG','google_drive')")
            )
            with pytest.raises(RuntimeError, match="Preserve Google Drive connection"):
                module.downgrade()
            assert "google_drive_transfers" in inspect(connection).get_table_names()
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
