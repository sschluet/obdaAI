"""Synthetic regression for explicit Vault remembering versus automatic learning."""

import asyncio
import uuid

import pytest
from hub.config import Settings
from hub.db import Base, Conversation, Memory, Message, Run
from hub.execution import execute_run
from hub.memory import encoded
from hub.memory_learning import reserve_learning
from hub.memory_models import MemoryLearningJob
from hub.memory_service import digest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from test_chat import FakeProviders


def test_explicit_legacy_vault_remember_does_not_schedule_a_second_memory(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = Settings(vault_dir=str(vault), vault_writable=True)
    with factory() as db:
        chat = Conversation()
        db.add(chat)
        db.flush()
        run = Run(conversation_id=chat.id, status="queued")
        db.add(run)
        db.flush()
        message = Message(
            conversation_id=chat.id,
            run_id=run.id,
            role="user",
            content="Merke dir: Ich arbeite als Ingenieur.",
        )
        db.add(message)
        db.commit()

    # Keep the actual queued learning intent inspectable without configuring any model.
    async def deferred(*args, **kwargs):
        return None

    monkeypatch.setattr("hub.memory_learning.execute_learning", deferred)
    asyncio.run(execute_run(factory, cfg, FakeProviders(), run.id))
    with factory() as db:
        rows = list(db.scalars(select(Memory)))
        assert len(rows) == 1 and rows[0].storage == "vault"
        assert rows[0].origin == f"chat:{message.id}:{message.revision}"
        assert rows[0].content == "# Explizites Chat-Memory\n\nIch arbeite als Ingenieur."
        assert (vault / rows[0].path).is_file()
        pending = list(db.scalars(select(MemoryLearningJob)))
        assert pending == [], (
            "Explicit current Vault write must suppress duplicate automatic learning"
        )
    engine.dispose()


@pytest.mark.parametrize(
    "change",
    [
        None,
        "origin",
        "content",
        "source_revision",
        "storage",
        "status",
        "deleted",
        "conflict",
        "digest",
        "base",
        "scope",
        "missing",
        "externalchanged",
        "marker",
        "writable",
    ],
)
def test_only_exact_current_server_origin_and_canonical_copy_suppress_learning(tmp_path, change):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    cfg = Settings(vault_dir=str(tmp_path), vault_writable=True)
    with factory() as db:
        chat = Conversation()
        db.add(chat)
        db.flush()
        run = Run(conversation_id=chat.id, status="succeeded")
        db.add(run)
        db.flush()
        message = Message(
            conversation_id=chat.id,
            run_id=run.id,
            role="user",
            content="Merke dir: Ich arbeite als Ingenieur.",
        )
        db.add(message)
        db.flush()
        identifier = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"hub-memory:{message.id}:{message.revision}")
        )
        content = "# Explizites Chat-Memory\n\nIch arbeite als Ingenieur."
        row = Memory(
            id=identifier,
            path=f"AI/Memory/{identifier}.md",
            storage="vault",
            origin=f"chat:{message.id}:{message.revision}",
            writable=True,
            revision=2,
            content=content,
            base_content=content,
            sha256=digest(content),
        )
        db.add(row)
        db.flush()
        note = tmp_path / row.path
        note.parent.mkdir(parents=True)
        note.write_text(encoded(row))
        if change == "origin":
            row.origin = "vault"
        elif change == "content":
            row.content = row.base_content = "A different current Vault statement"
            row.sha256 = digest(row.content)
            note.write_text(encoded(row))
        elif change == "source_revision":
            message.revision += 1
        elif change == "storage":
            row.storage = "app"
        elif change == "status":
            row.status = "superseded"
        elif change == "deleted":
            row.deleted = True
        elif change == "conflict":
            row.conflict = "pending:synthetic"
        elif change == "digest":
            row.sha256 = "bad-digest"
        elif change == "base":
            row.base_content = "old base"
        elif change == "scope":
            row.project_id = "another-project"
        elif change == "missing":
            note.unlink()
        elif change == "externalchanged":
            note.write_text("Externally changed canonical note")
        elif change == "marker":
            note.write_text(content)
        elif change == "writable":
            row.writable = False
        db.commit()
        job = reserve_learning(db, cfg, run.id)
        assert (job is None) is (change is None)
    engine.dispose()
