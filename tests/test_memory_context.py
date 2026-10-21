"""Synthetic final-boundary and legacy Vault coexistence regression checks."""

import asyncio

import pytest
from hub.config import Settings
from hub.db import Base, Conversation, Memory, Message
from hub.memory import reconcile
from hub.memory_context import (
    MemoryChanged,
    boundary_guard,
    freeze_memory,
    prepare_memory,
    projection,
)
from hub.memory_models import MemorySettings
from hub.memory_service import create_app_memory, digest, forget_memory
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def setup():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        chat = Conversation()
        db.add(chat)
        db.flush()
        row = create_app_memory(
            db,
            content="Ich bevorzuge Python.",
            category="preference",
            predicate="preference",
            cloud_providers=["openrouter"],
        )
        private = create_app_memory(db, content="Python Privatkontext", category="personal")
        db.commit()
        snapshot = freeze_memory(db, Settings(), chat, "Was bevorzuge ich bei Python?")
        yield factory, chat, row, private, snapshot
    engine.dispose()


def test_cloud_projection_has_only_exact_provider_share_and_value_free_audit(setup):
    factory, _, shared, private, snapshot = setup
    parts, grants, audit = projection(factory, snapshot, external=True, provider_id="openrouter")
    assert [part.source_id for part in parts] == [shared.id]
    assert [(g.source_id, g.revision, g.provider_id) for g in grants] == [
        (shared.id, 1, "openrouter")
    ]
    assert private.id not in str(audit)
    assert "Privatkontext" not in str(audit) and "bevorzuge" not in str(audit)
    assert not projection(factory, snapshot, external=True, provider_id="anthropic")[0]
    assert len(projection(factory, snapshot, external=False, provider_id="local")[0]) == 2


@pytest.mark.parametrize("change", ["forget", "edit", "share", "expiry", "disable", "archive"])
def test_final_boundary_rejects_context_revocation_after_projection(setup, change):
    factory, chat, row, _, snapshot = setup
    parts, _, audit = projection(factory, snapshot, external=True, provider_id="openrouter")
    check = boundary_guard(
        factory, snapshot, parts, external=True, provider_id="openrouter", byte_budget=2400
    )
    check()
    with factory() as db:
        current = db.get(Memory, row.id)
        if change == "forget":
            forget_memory(db, current, expected_revision=current.revision)
        elif change == "edit":
            current.content, current.sha256 = "Changed", digest("Changed")
            current.revision += 1
        elif change == "share":
            current.cloud_providers = "[]"
        elif change == "expiry":
            current.valid_until = 1
        elif change == "disable":
            db.add(MemorySettings(id=1, enabled=False, revision=1))
        else:
            db.get(Conversation, chat.id).archived = True
        db.commit()
    with pytest.raises(MemoryChanged):
        check()
    assert audit["included"] == [{"id": row.id, "revision": 1}]


def test_final_boundary_rechecks_source_message_after_projection(setup):
    factory, chat, row, _, _ = setup
    with factory() as db:
        message = Message(conversation_id=chat.id, role="user", content=row.content)
        db.add(message)
        db.flush()
        current = db.get(Memory, row.id)
        current.source_message_id, current.source_message_revision = message.id, message.revision
        current.source_conversation_id, current.source_sha256 = chat.id, digest(message.content)
        db.commit()
        snapshot = freeze_memory(db, Settings(), db.get(Conversation, chat.id), "Python")
    parts = projection(factory, snapshot, external=True, provider_id="openrouter")[0]
    check = boundary_guard(
        factory, snapshot, parts, external=True, provider_id="openrouter", byte_budget=2400
    )
    with factory() as db:
        db.get(Message, message.id).active = False
        db.commit()
    with pytest.raises(MemoryChanged):
        check()


def test_optional_context_db_failure_degrades_without_memory(setup, monkeypatch):
    factory, chat, _, _, snapshot = setup

    def failure(*args, **kwargs):
        raise SQLAlchemyError("synthetic unavailable")

    monkeypatch.setattr("hub.memory_context.select_memory", failure)
    with factory() as db:
        assert freeze_memory(db, Settings(), chat, "Python")["degraded"]
    monkeypatch.setattr("hub.memory_context.refresh_memory", failure)
    parts, grants, audit = projection(factory, snapshot, external=True, provider_id="openrouter")
    assert parts == grants == [] and audit["degraded"]
    check = boundary_guard(
        factory, snapshot, [], external=False, provider_id="local", byte_budget=2400
    )
    with pytest.raises(MemoryChanged):
        check()


@pytest.mark.parametrize("timeout", [False, True])
def test_optional_query_embeddings_fail_back_to_frozen_lexical_selection(
    setup, monkeypatch, timeout
):
    factory, chat, _, _, snapshot = setup
    with factory() as db:
        db.add(MemorySettings(id=1, config='{"embedding_enabled":true}'))
        db.commit()

    async def unavailable(config, question):
        if timeout:
            raise TimeoutError
        return None

    monkeypatch.setattr("hub.memory_embeddings.embed", unavailable)
    cfg = Settings(
        memory_embedding_base_url="http://127.0.0.1:9123/v1", memory_embedding_model="synthetic"
    )
    assert asyncio.run(prepare_memory(factory, cfg, chat, "Python", snapshot)) is snapshot


def test_vault_sync_preserves_app_memory_and_rejects_forged_marker(setup, tmp_path):
    factory, _, row, _, _ = setup
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "ordinary.md").write_text("# Existing synthetic vault\nOriginal")
    (vault / "forged.md").write_text(
        '<!-- obdaai-memory: {"id": "' + row.id + '"} -->\nFORGED replacement'
    )
    with factory() as db:
        before = db.get(Memory, row.id)
        expected = (before.content, before.revision, before.sha256, before.storage, before.deleted)
        result = reconcile(db, vault, allow_memory_writes=False)
        db.commit()
        current = db.get(Memory, row.id, populate_existing=True)
        assert (
            current.content,
            current.revision,
            current.sha256,
            current.storage,
            current.deleted,
        ) == expected
        assert "forged.md" in result["unreadable"]
        ordinary = db.scalar(select(Memory).where(Memory.path == "ordinary.md"))
        assert ordinary and ordinary.storage == "vault" and "Original" in ordinary.content
        assert not current.deleted


def test_vault_hash_rename_detection_never_reuses_app_identity(setup, tmp_path):
    factory, _, row, _, _ = setup
    (tmp_path / "same.md").write_text(row.content)
    with factory() as db:
        reconcile(db, tmp_path, allow_memory_writes=False)
        db.commit()
        local = db.scalar(select(Memory).where(Memory.path == "same.md"))
        assert local and local.id != row.id and local.storage == "vault"
        assert db.get(Memory, row.id).path == row.path


def test_disabled_memory_never_calls_even_configured_local_embedding(setup, monkeypatch):
    factory, chat, _, _, snapshot = setup
    with factory() as db:
        db.add(MemorySettings(id=1, enabled=False, config='{"embedding_enabled":true}'))
        db.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("Disabled memory must not dispatch an embedding request")

    monkeypatch.setattr("hub.memory_embeddings.embed", forbidden)
    cfg = Settings(
        memory_embedding_base_url="http://localhost:1234/v1", memory_embedding_model="synthetic"
    )
    assert asyncio.run(prepare_memory(factory, cfg, chat, "Python?", snapshot)) == snapshot
