"""Real authenticated chat path with synthetic models and app-owned memory."""

import asyncio
import json

import pytest
from hub import memory_context, memory_learning
from hub.db import Memory, Run
from hub.memory_models import MemoryLearningJob
from hub.memory_service import create_app_memory
from hub.policy import ContextPart
from hub.routing import Route
from sqlalchemy import select
from test_chat import FakeProviders, new_chat

pytest_plugins = ["test_chat"]


class RecordingProvider(FakeProviders):
    def __init__(self, cloud=False):
        super().__init__(
            Route(
                capabilities=["chat"], model_class="cloud" if cloud else "local", reason="fixture"
            )
        )
        self.routed = []
        self.answered = []

    async def route(self, parts, roles):
        self.routed.extend(parts)
        return await super().route(parts, roles)

    async def stream(self, parts, roles, **kwargs):
        self.answered.extend(parts)
        async for chunk in super().stream(parts, roles, **kwargs):
            yield chunk


def ask(client, headers, chat_id, content, **extra):
    result = client.post(
        f"/api/conversations/{chat_id}/messages",
        headers=headers,
        json={"content": content, **extra},
    )
    assert result.status_code == 200, result.text
    assert '"status": "succeeded"' in result.text, result.text
    return result


@pytest.mark.parametrize(
    "cloud,shared,explicit,expected,actual_cloud",
    [
        (False, False, False, True, False),
        (True, False, False, True, False),
        (True, False, True, False, True),
        (True, True, False, True, True),
    ],
)
def test_memory_before_answer_independent_from_route_and_exact_sharing(
    setup, cloud, shared, explicit, expected, actual_cloud
):
    app, client, headers, _ = setup
    provider = RecordingProvider(cloud)
    app.state.providers = provider
    with app.state.sessions() as db:
        row = create_app_memory(
            db,
            content="Ich arbeite als SYNTHETIC_MEMORY_CAREER.",
            predicate="profession",
            cloud_providers=["openrouter"] if shared else [],
        )
        db.commit()
        memory_id = row.id
    chat = new_chat(client, headers, cloud)
    ask(client, headers, chat, "Welcher Beruf passt zu mir?", model_cloud_only=explicit)
    assert all("SYNTHETIC_MEMORY_CAREER" not in p.content for p in provider.routed)
    assert any("SYNTHETIC_MEMORY_CAREER" in p.content for p in provider.answered) == expected
    assert provider.stream_calls == [actual_cloud]
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == chat))
        included = json.loads(run.routing_trace)["memory"]["included"]
        assert any(i["id"] == memory_id for i in included) == expected
        # Context construction preserves the ordinary admitted user/source snapshot.
        snapshot = json.loads(run.context_snapshot)
        assert snapshot["memory_source"]["id"]
        assert snapshot["memory_used"]["used_bytes"] <= 2400


def test_unrelated_memory_never_added_and_failure_does_not_break_chat(setup, monkeypatch):
    app, client, headers, _ = setup
    provider = RecordingProvider()
    app.state.providers = provider
    with app.state.sessions() as db:
        create_app_memory(db, content="Ich sammle SYNTHETIC_STAMPS.", predicate="interest")
        db.commit()
    ask(client, headers, new_chat(client, headers), "Wie funktioniert SQL?")
    assert all("SYNTHETIC_STAMPS" not in p.content for p in provider.answered)

    def broken(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION")

    monkeypatch.setattr(memory_context, "select_memory", broken)
    result = ask(client, headers, new_chat(client, headers), "Welche Hobbys habe ich?")
    assert "SYNTHETIC_PRIVATE_EXCEPTION" not in result.text


def test_complete_chat_learning_then_retrieval_in_another_conversation(setup, monkeypatch):
    app, client, headers, _ = setup
    provider = RecordingProvider()
    app.state.providers = provider
    real_execute = memory_learning.execute_learning

    async def leave_queued(*args, **kwargs):
        pass  # Exercise the exact durable job after the HTTP response, deterministically.

    monkeypatch.setattr(memory_learning, "execute_learning", leave_queued)
    original_chat = new_chat(client, headers)
    source = "Ich arbeite als SYNTHETIC_ENGINEER."
    ask(client, headers, original_chat, source)
    with app.state.sessions() as db:
        job = db.scalar(select(MemoryLearningJob))
        assert job and job.status == "queued"
        job_id = job.id

    class Extractor:
        async def stream(self, parts: list[ContextPart], roles, **kwargs):
            assert not kwargs["external"] and parts[-1].content == source
            yield json.dumps(
                {"facts": [{"quote": source, "predicate": "profession", "confidence": 0.99}]}
            )

    asyncio.run(real_execute(app.state.sessions, app.state.settings, job_id, Extractor()))
    with app.state.sessions() as db:
        job = db.get(MemoryLearningJob, job_id)
        assert job.status == "succeeded"
        learned = db.scalar(select(Memory).where(Memory.storage == "app"))
        assert learned and learned.source_message_id == job.source_message_id
        assert learned.cloud_providers == "[]"
    provider.answered.clear()
    ask(client, headers, new_chat(client, headers), "Welchen Beruf habe ich?")
    assert any(source in p.content for p in provider.answered)
    assert all(
        source not in p.content for p in provider.routed if p.source_id != job.source_message_id
    )


def test_summary_survives_learning_failure_and_is_later_used(setup, monkeypatch):
    from hub.db import Message
    from hub.memory_summary import ConversationSummary

    app, client, headers, _ = setup
    provider = RecordingProvider()
    app.state.providers = provider
    chat = new_chat(client, headers)
    with app.state.sessions() as db:
        db.add_all(
            [
                Message(
                    conversation_id=chat,
                    role="user" if index % 2 else "assistant",
                    content=f"SYNTHETIC_OLDER_DECISION {index}",
                    created=float(index),
                )
                for index in range(12)
            ]
        )
        db.commit()

    def unavailable(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_OPTIONAL_JOB_FAILURE")

    monkeypatch.setattr(memory_learning, "reserve_learning", unavailable)
    ask(client, headers, chat, "Wie funktioniert eine Warteschlange?")
    with app.state.sessions() as db:
        summary = db.get(ConversationSummary, chat)
        assert summary and "SYNTHETIC_OLDER_DECISION" in summary.content
    provider.answered.clear()
    result = ask(client, headers, chat, "Fahre mit der Erklärung fort.")
    assert any(p.source_id == "summary:" + chat for p in provider.answered)
    assert "SYNTHETIC_OPTIONAL_JOB_FAILURE" not in result.text
