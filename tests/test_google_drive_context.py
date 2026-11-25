"""Revocation of cached Drive context is enforced at the actual model boundary."""

import asyncio
import json

import httpx
import pytest
from hub.budgets import ExecutionLimitError
from hub.config import Settings
from hub.db import (
    Base,
    Conversation,
    KnowledgeConnection,
    Memory,
    Message,
    Project,
    ProviderConfig,
    Run,
)
from hub.execution import execute_run
from hub.google_drive_context import check_source, freeze_source
from hub.integrations import Integration
from hub.knowledge_clients import ConnectionInput
from hub.memory_context import freeze_memory
from hub.memory_service import create_app_memory
from hub.policy import ContextPart
from hub.provider_settings import seed
from hub.providers import Providers
from hub.routing import Route
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def cached():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    cfg = Settings(local_model="synthetic-model", cloud_enabled=False)
    with factory() as db:
        project = Project(name="Synthetic Drive context", kind="knowledge")
        profile = Integration(
            name="Synthetic Drive",
            kind="google_drive",
            revision=3,
            enabled=True,
            writes_enabled=False,
            encrypted_secret="synthetic-encrypted-reference",
            config=json.dumps(
                {
                    "kind": "google_drive",
                    "url": "https://www.googleapis.com/drive/v3",
                    "auth": "oauth",
                    "connected": True,
                    "enable_source": True,
                    "enable_storage": False,
                    "source_folder_id": "root",
                    "account_email": "aurora@example.test",
                }
            ),
        )
        db.add_all([project, profile])
        db.flush()
        body = ConnectionInput(
            name="Synthetic Drive context",
            kind="google_drive",
            server="www.googleapis.com",
            folder="root",
            integration_id=profile.id,
            integration_revision=profile.revision,
        )
        connection = KnowledgeConnection(
            name=body.name,
            kind="google_drive",
            address=body.server,
            target_ref=profile.id,
            project_id=project.id,
            revision=4,
            status="ready",
            enabled=True,
            config=json.dumps(body.public()),
        )
        db.add(connection)
        db.flush()
        frozen = freeze_source(db, project.id)
        seed(db, cfg)
        db.commit()
        yield factory, cfg, project.id, profile.id, connection.id, frozen
    engine.dispose()


def revoke(db, kind, project_id, profile_id, connection_id):
    connection = db.get(KnowledgeConnection, connection_id)
    profile = db.get(Integration, profile_id)
    if kind == "integration_off":
        profile.enabled = False
    elif kind == "connection_off":
        connection.enabled = False
    elif kind == "scope_change":
        config = json.loads(connection.config)
        config["folder"] = "other_folder"
        connection.config = json.dumps(config)
        connection.revision += 1
    elif kind == "account_revision":
        config = json.loads(profile.config)
        config["account_email"] = "other@example.test"
        profile.config = json.dumps(config)
        profile.revision += 1
    elif kind == "source_permission":
        config = json.loads(profile.config)
        config["enable_source"] = False
        profile.config = json.dumps(config)
    elif kind == "connection_delete":
        db.delete(connection)
    elif kind == "project_archive":
        db.get(Project, project_id).archived = True
    elif kind == "project_rebind":
        connection.project_id = "other-project"
    else:
        raise AssertionError(kind)
    db.commit()


@pytest.mark.parametrize(
    "kind",
    [
        "integration_off",
        "connection_off",
        "scope_change",
        "account_revision",
        "source_permission",
        "connection_delete",
        "project_archive",
        "project_rebind",
    ],
)
def test_frozen_cache_reloads_authority_and_rejects_revocation(cached, kind):
    factory, _, project_id, profile_id, connection_id, frozen = cached
    check_source(factory, frozen)
    with factory() as stale:
        original = stale.get(KnowledgeConnection, connection_id)
        with factory() as db:
            revoke(db, kind, project_id, profile_id, connection_id)
        assert original.enabled is True  # Identity-cached data must not authorize dispatch.
        with pytest.raises(ExecutionLimitError):
            check_source(factory, frozen)


@pytest.mark.parametrize("with_memory", [False, True])
@pytest.mark.parametrize(
    "kind",
    [
        "integration_off",
        "connection_off",
        "scope_change",
        "account_revision",
        "connection_delete",
        "project_archive",
    ],
)
def test_actual_provider_slot_wait_revocation_prevents_any_http(
    cached, monkeypatch, kind, with_memory
):
    factory, cfg, project_id, profile_id, connection_id, frozen = cached
    requests = []
    original_client = httpx.AsyncClient

    def reply(request):
        requests.append(request)
        return httpx.Response(200, text="data: [DONE]\n\n")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(reply)),
    )
    provider = Providers(cfg)

    async def route(*args):
        return Route(
            capabilities=["chat"], model_class="local", reason="Synthetic local source question"
        )

    monkeypatch.setattr(provider, "route", route)
    monkeypatch.setattr(
        provider, "_target", lambda *args: ("http://127.0.0.1/v1/chat/completions", {}, {}, "")
    )
    with factory() as db:
        selected = {"local": db.get(ProviderConfig, "local-default")}
        chat = Conversation(
            project_id=project_id, title="Synthetic preserved title", cloud_allowed=False
        )
        db.add(chat)
        db.flush()
        message = Message(
            conversation_id=chat.id,
            role="user",
            content="Fasse die ausgewählte Quelle zusammen.",
            label="LOCAL_ONLY",
        )
        db.add(message)
        db.flush()
        source = ContextPart(
            content="QUELLE [synthetic-drive-1] Private synthetic cached document",
            source_id="synthetic-drive-1",
            revision=1,
        )
        snapshot = {
            "parts": [
                ContextPart(content=message.content, source_id=message.id, revision=1).model_dump(
                    mode="json"
                ),
                source.model_dump(mode="json"),
            ],
            "roles": ["user", "user"],
            "sources": [source.model_dump(mode="json")],
            "google_drive_source": frozen,
            "integration_selection": {"effective_mode": "automatic", "bindings": []},
            "model_local_only": True,
            "model_cloud_only": False,
            "web_search_allowed": False,
        }
        if with_memory:
            # Ordinary project contexts can contain both cached Drive data and memory.
            # Hidden knowledge projects intentionally omit generic personal memory.
            db.get(Project, project_id).kind = "project"
            create_app_memory(
                db,
                content="Ich bevorzuge kurze Antworten.",
                category="preference",
                predicate="preference",
                subject="response_style",
            )
            snapshot["memory"] = freeze_memory(db, cfg, chat, message.content)
            assert snapshot["memory"]["items"]
        run = Run(conversation_id=chat.id, status="queued", context_snapshot=json.dumps(snapshot))
        db.add(run)
        db.commit()
        identifier = run.id
    monkeypatch.setattr(
        "hub.execution.runtime_provider", lambda *args, **kwargs: (cfg, provider, selected)
    )

    async def exercise():
        waiting = asyncio.Event()

        class WaitingSlot(asyncio.Semaphore):
            entries = 0

            async def __aenter__(self):
                self.entries += 1
                if with_memory and self.entries == 1:
                    assert provider.before_send.__qualname__.endswith("guard")
                waiting.set()
                if kind == "memory_retry" and self.entries == 2:
                    with factory() as db:
                        revoke(db, "integration_off", project_id, profile_id, connection_id)
                return await super().__aenter__()

        provider.local_slot = WaitingSlot(0)
        task = asyncio.create_task(execute_run(factory, cfg, provider, identifier))
        await asyncio.wait_for(waiting.wait(), timeout=3)
        with factory() as db:
            if kind == "memory_retry":
                memory = db.scalar(select(Memory).where(Memory.storage == "app"))
                memory.revision += 1
                db.commit()
            else:
                revoke(db, kind, project_id, profile_id, connection_id)
        provider.local_slot.release()
        await asyncio.wait_for(task, timeout=3)

    asyncio.run(exercise())
    assert requests == []
    assert provider.before_send is None  # The next conversation has its own authority.
    with factory() as db:
        run = db.get(Run, identifier)
        # The project-model gate rejects an archived project before Drive egress.
        expected_error = ("Projekt fehlt oder ist archiviert"
                          if kind == "project_archive" else "Google-Drive")
        assert run.status == "failed" and expected_error in run.error
        assert all(
            "Private synthetic cached document" not in message.content
            for message in db.scalars(select(Message).where(Message.run_id == identifier))
        )


def test_memory_degradation_retry_restores_drive_guard_after_slot(cached, monkeypatch):
    test_actual_provider_slot_wait_revocation_prevents_any_http(
        cached, monkeypatch, "memory_retry", True
    )
