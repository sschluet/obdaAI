"""Synthetic local transport checks for the private interpreter's final boundary."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from hub.agent_intent import RequestIntent, Requirement
from hub.db import Conversation, ProviderConfig, Run
from hub.request_interpretation import interpret
from sqlalchemy import select

pytest_plugins = ["test_provider_settings"]


@pytest.mark.parametrize("change", [None, "disable", "revision", "default", "cancel", "owner"])
def test_private_interpreter_rechecks_provider_and_run_after_capacity_wait(
    managed, monkeypatch, change
):
    app, _, _, cfg = managed
    profiles = {"synthetic-ha": SimpleNamespace(kind="home_assistant", name="Synthetic HA")}
    with app.state.sessions() as db:
        owner = Conversation(title="Synthetic interpretation owner")
        db.add(owner)
        db.commit()
        owner_id = owner.id
    original = httpx.AsyncClient
    sent = []

    def handler(request):
        body = json.loads(request.content)
        assert body["temperature"] == 0 and body["enable_thinking"] is False
        assert body["max_tokens"] == 768
        assert all(
            "LOCAL_ONLY" in text or "Interpret" in text or "Classify" in text
            for text in [body["messages"][1]["content"]]
        )
        sent.append(True)
        result = RequestIntent(
            mode="observe",
            topic="inventory",
            target_ids=["synthetic-ha"],
            requirements=[
                Requirement(kind="entity_states", domain="light", integration_id="synthetic-ha")
            ],
        )
        return httpx.Response(
            200,
            text="data: "
            + json.dumps({"choices": [{"delta": {"content": result.model_dump_json()}}]})
            + "\n\ndata: [DONE]\n\n",
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )

    @asynccontextmanager
    async def wait_then_change(*args):
        if change:
            with app.state.sessions() as db:
                provider = db.get(ProviderConfig, "local-default")
                run = db.scalar(select(Run).where(Run.status == "streaming"))
                if change == "disable":
                    provider.enabled = False
                elif change == "revision":
                    provider.revision += 1
                elif change == "default":
                    provider.is_default = False
                elif change == "cancel":
                    run.cancel_requested = True
                elif change == "owner":
                    db.get(Conversation, owner_id).archived = True
                db.commit()
        yield

    monkeypatch.setattr("hub.providers.local_capacity", wait_then_change)
    if change:
        with pytest.raises(PermissionError):
            asyncio.run(
                interpret(
                    app.state.sessions,
                    cfg,
                    "Synthetic current light request",
                    profiles,
                    conversation_id=owner_id,
                )
            )
        assert not sent
    else:
        result = asyncio.run(
            interpret(
                app.state.sessions,
                cfg,
                "Synthetic current light request",
                profiles,
                conversation_id=owner_id,
            )
        )
        assert result.mode == "observe" and len(sent) == 1
    with app.state.sessions() as db:
        run = db.scalar(select(Run))
        conversation = db.get(Conversation, run.conversation_id)
        assert conversation.archived and conversation.purpose == "intent"
        assert run.status == (
            "succeeded" if not change else "cancelled" if change == "cancel" else "failed"
        )
        assert run.finished is not None
        assert json.loads(run.context_snapshot)["request_owner"] == owner_id
