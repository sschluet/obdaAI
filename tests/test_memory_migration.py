"""Real additive 0045→0046 migration, persistence and downgrade loss prevention."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from hub.db import Conversation, Memory, Message, PersonalProfile
from hub.memory_embeddings import MemoryEmbedding
from hub.memory_models import MemoryCandidate, MemoryLearningJob, MemorySettings
from hub.memory_service import create_app_memory, digest
from hub.memory_summary import ConversationSummary
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "memory-migration.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "0045")
    engine = create_engine(url)
    memory_id = str(uuid4())
    content = "# Synthetic original vault\n\nPreserve this exact synthetic note."
    with Session(engine) as db:
        chat = Conversation(title="Synthetic preserved chat", cloud_allowed=False)
        db.add(chat)
        db.flush()
        message = Message(
            conversation_id=chat.id,
            role="user",
            revision=3,
            content="Synthetic original message",
            label="LOCAL_ONLY",
        )
        db.add(message)
        profile = db.get(PersonalProfile, 1)
        profile.revision = 7
        profile.enabled = True
        profile.fields = '{"name":"Synthetic preserved profile"}'
        profile.cloud_fields = "[]"
        db.commit()
        chat_id, message_id = chat.id, message.id
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO memories (id,origin,path,project_id,label,revision,sha256,content,"
                "base_content,conflict,deleted,writable,updated) VALUES "
                "(:id,'vault','AI/Memory/synthetic-original.md',NULL,'LOCAL_ONLY',9,:sha,:body,"
                ":body,'',false,true,12345)"
            ),
            {"id": memory_id, "sha": digest(content), "body": content},
        )
        connection.execute(
            text(
                "INSERT INTO memory_revisions (memory_id,revision,content,sha256,created) "
                "VALUES (:id,9,:body,:sha,12345)"
            ),
            {"id": memory_id, "sha": digest(content), "body": content},
        )
        preserved = snapshot(connection)
    engine.dispose()
    command.upgrade(Config("alembic.ini"), "0046")
    yield url, memory_id, chat_id, message_id, preserved


def snapshot(connection):
    return {
        table: [dict(row) for row in connection.execute(text("SELECT * FROM " + table)).mappings()]
        for table in (
            "memories",
            "memory_revisions",
            "personal_profile",
            "conversations",
            "messages",
        )
    }


def verify_preserved(connection, originals):
    current = snapshot(connection)
    for table, rows in originals.items():
        assert len(current[table]) == len(rows), table
        for before, after in zip(rows, current[table], strict=True):
            assert {key: after[key] for key in before} == before, table


def test_additive_migration_preserves_existing_vault_profile_chat_and_revisions(migrated):
    url, memory_id, _, _, originals = migrated
    engine = create_engine(url)
    with engine.connect() as connection:
        verify_preserved(connection, originals)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0046"
        row = (
            connection.execute(text("SELECT * FROM memories WHERE id=:id"), {"id": memory_id})
            .mappings()
            .one()
        )
        assert row["storage"] == "vault" and row["owner_id"] == "owner"
        assert row["status"] == "active" and row["category"] == "knowledge"
        assert row["fact_type"] == "fact" and row["confidence"] == 1
        assert row["sensitivity"] == "private" and row["cloud_providers"] == "[]"
        assert row["source_message_id"] is None and row["source_sha256"] == ""
        assert set(inspect(connection).get_table_names()) >= {
            "memory_settings",
            "memory_candidates",
            "memory_learning_jobs",
            "memory_embeddings",
            "conversation_summaries",
        }
    engine.dispose()


def test_native_memory_persists_across_reopened_database_and_guarded_downgrade(migrated):
    url, legacy_id, _, _, _ = migrated
    engine = create_engine(url)
    with Session(engine) as db:
        native = create_app_memory(db, content="Synthetic durable native memory", title="Native")
        db.commit()
        native_id, native_sha = native.id, native.sha256
    engine.dispose()
    restarted = create_engine(url)
    with Session(restarted) as db:
        native = db.get(Memory, native_id)
        assert (
            native.storage == "app"
            and native.content == "# Native\n\nSynthetic durable native memory"
        )
        assert native.sha256 == native_sha and native.revision == 1
        assert db.get(Memory, legacy_id).revision == 9
    restarted.dispose()
    with pytest.raises(RuntimeError, match="Preserve app-native memories"):
        command.downgrade(Config("alembic.ini"), "0045")
    after = create_engine(url)
    with after.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0046"
        assert (
            connection.scalar(text("SELECT sha256 FROM memories WHERE id=:id"), {"id": native_id})
            == native_sha
        )
    after.dispose()


@pytest.mark.parametrize("table", ["settings", "candidate", "job", "embedding", "summary"])
def test_downgrade_refuses_each_kind_of_new_state_before_dropping_any_table(migrated, table):
    url, memory_id, chat_id, message_id, originals = migrated
    engine = create_engine(url)
    with Session(engine) as db:
        pointer = dict(
            source_message_id=message_id,
            source_message_revision=3,
            source_conversation_id=chat_id,
            source_sha256=digest("Synthetic original message"),
        )
        if table == "settings":
            row = MemorySettings(id=1)
        elif table == "candidate":
            row = MemoryCandidate(**pointer, quote_start=0, quote_end=9)
        elif table == "job":
            row = MemoryLearningJob(**pointer, settings_revision=0)
        elif table == "embedding":
            row = MemoryEmbedding(
                memory_id=memory_id,
                revision=9,
                sha256="a" * 64,
                model="synthetic",
                config_sha256="b" * 64,
                dimensions=1,
                vector="[1]",
            )
        else:
            row = ConversationSummary(
                conversation_id=chat_id,
                owner_id="owner",
                revision=1,
                source_snapshot="[]",
                content="Synthetic derived summary",
                label="LOCAL_ONLY",
                sha256="c" * 64,
            )
        db.add(row)
        db.commit()
    engine.dispose()
    with pytest.raises(RuntimeError, match="Preserve memory state"):
        command.downgrade(Config("alembic.ini"), "0045")
    after = create_engine(url)
    with after.connect() as connection:
        verify_preserved(connection, originals)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0046"
        assert "memory_settings" in inspect(connection).get_table_names()
    after.dispose()


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PG required")
def test_additive_memory_migration_actual_postgres_preserves_existing_rows(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci is allowed")
    engine = create_engine(url)
    schema = "memory_migration_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        spec = importlib.util.spec_from_file_location(
            "intelligent_memory_migration", Path("migrations/versions/0046_intelligent_memory.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
            connection.execute(text("CREATE TABLE conversations (id varchar(36) PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE memories (id varchar(36) PRIMARY KEY, "
                    "project_id varchar(36), content text, sha256 varchar(64), "
                    "revision integer, label text)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO memories VALUES "
                    "('synthetic',NULL,'PRESERVED SYNTHETIC VAULT',:sha,9,'LOCAL_ONLY')"
                ),
                {"sha": digest("PRESERVED SYNTHETIC VAULT")},
            )
            module.upgrade()
            row = connection.execute(text("SELECT * FROM memories")).mappings().one()
            assert row["content"] == "PRESERVED SYNTHETIC VAULT" and row["revision"] == 9
            assert row["sha256"] == digest(row["content"]) and row["label"] == "LOCAL_ONLY"
            assert row["storage"] == "vault" and row["status"] == "active"
            connection.execute(text("UPDATE memories SET storage='app' WHERE id='synthetic'"))
            with pytest.raises(RuntimeError, match="Preserve app-native"):
                module.downgrade()
            assert "conversation_summaries" in inspect(connection).get_table_names()
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
