"""Real transport adapters reject revoked memory before any HTTP request."""

import asyncio
import json

import httpx
import pytest
from hub.config import Settings
from hub.db import Base, Conversation, Message, ProviderConfig, Run
from hub.memory_context import MemoryChanged
from hub.memory_learning import execute_learning, reserve_learning
from hub.memory_models import MemoryLearningJob, MemorySettings
from hub.native_providers import REVIEWED_AT, NativeConfig, NativeProvider
from hub.policy import CloudGrant, ContextPart
from hub.providers import Providers
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def transport(monkeypatch):
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="data: [DONE]\n\n")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)),
    )
    return requests


def deny():
    raise MemoryChanged("synthetic revoked")


def test_generic_local_adapter_checks_before_transport(monkeypatch):
    requests = transport(monkeypatch)
    provider = Providers(Settings(local_model="synthetic-model"))
    provider.before_send = deny

    async def run():
        return [
            piece
            async for piece in provider.stream(
                [ContextPart(content="synthetic private", source_id="m", revision=1)],
                ["user"],
                external=False,
                grants=[],
            )
        ]

    with pytest.raises(MemoryChanged):
        asyncio.run(run())
    assert requests == []


@pytest.mark.parametrize(
    "kind,model", [("openai", "gpt-4.1-mini"), ("anthropic", "claude-haiku-4-5-20251001")]
)
def test_native_adapter_final_callback_prevents_http(monkeypatch, kind, model):
    requests = transport(monkeypatch)
    monkeypatch.setattr("hub.native_providers.time.time", lambda: REVIEWED_AT + 3600)
    monkeypatch.setattr(
        "hub.native_providers.pinned_url", lambda *a, **k: ("https://1.1.1.1/v1/synthetic", {}, {})
    )
    provider = NativeProvider(NativeConfig(kind, model, enabled=True), "synthetic-key")
    provider.before_send = deny

    async def run():
        return [
            piece
            async for piece in provider.stream(
                [
                    ContextPart(
                        content="synthetic shared", label="CLOUD_ALLOWED", source_id="m", revision=1
                    )
                ],
                ["user"],
                grants=[CloudGrant(source_id="m", revision=1, provider_id=kind)],
            )
        ]

    with pytest.raises(MemoryChanged):
        asyncio.run(run())
    assert requests == []


@pytest.mark.parametrize("revoke", ["source", "settings", "cancel", "taskcancel"])
def test_learning_final_source_check_after_local_slot_wait(monkeypatch, revoke):
    requests = transport(monkeypatch)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    cfg = Settings(local_model="synthetic-model")
    with factory() as db:
        chat = Conversation()
        db.add(chat)
        db.flush()
        run = Run(conversation_id=chat.id, status="succeeded")
        db.add(run)
        db.flush()
        # Exercise the optional model path, outside exact literal-role parsing.
        message = Message(
            conversation_id=chat.id,
            run_id=run.id,
            role="user",
            content="Ich arbeite bei einer Firma.",
        )
        db.add(message)
        db.add(
            ProviderConfig(
                id="synthetic-local",
                kind="local",
                name="Synthetic",
                enabled=True,
                is_default=True,
                config=json.dumps(
                    {"output_tokens": 1000, "context_chars": 24000, "context_tokens": 32768}
                ),
            )
        )
        db.flush()
        identifier = reserve_learning(db, cfg, run.id)
        assert identifier
        db.commit()
    provider = Providers(cfg)
    monkeypatch.setattr("hub.provider_api.adapter", lambda *a, **k: provider)
    monkeypatch.setattr(
        provider, "_target", lambda external: ("http://127.0.0.1/v1/chat/completions", {}, {}, "")
    )

    async def exercise():
        waiting = asyncio.Event()

        class WaitingSlot(asyncio.Semaphore):
            async def __aenter__(self):
                waiting.set()
                return await super().__aenter__()

        provider.local_slot = WaitingSlot(0)
        task = asyncio.create_task(execute_learning(factory, cfg, identifier))
        await asyncio.wait_for(waiting.wait(), timeout=2)
        with factory() as db:
            if revoke == "source":
                db.get(Message, message.id).active = False
            elif revoke == "settings":
                db.add(MemorySettings(id=1, enabled=False, revision=1))
            elif revoke == "cancel":
                db.get(Run, run.id).cancel_requested = True
            db.commit()
        if revoke == "taskcancel":
            task.cancel()
        provider.local_slot.release()
        if revoke == "taskcancel":
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
        else:
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(exercise())
    with factory() as db:
        learning = db.get(MemoryLearningJob, identifier)
        expected = (
            "worker_interrupted" if revoke == "taskcancel" else "local_extraction_unavailable"
        )
        assert learning.status == "failed" and learning.error == expected
    assert requests == []
    engine.dispose()
