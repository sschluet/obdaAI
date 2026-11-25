"""Real local adapter + synthetic HTTP transport: revoke during capacity wait."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from hub.config import Settings
from hub.db import Conversation, Message, ProviderConfig
from hub.inference_capacity import local_capacity
from hub.policy import ContextPart
from hub.providers import Providers
from hub.titles import execute_title
from sqlalchemy import select
from test_chat import new_chat
from test_titles import pending

pytest_plugins = ["test_chat"]


def transport(monkeypatch, respond=None):
    calls = []
    original = httpx.AsyncClient

    def handle(request):
        calls.append(request)
        content = respond() if respond else {"title": "Synthetic generated title"}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
        )

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    return calls


@pytest.mark.parametrize("role", ["route", "title"])
def test_real_role_adapter_rechecks_hook_after_capacity_queue(monkeypatch, tmp_path, role):
    calls = transport(monkeypatch)
    cfg = Settings(
        source_dir=str(tmp_path), local_base_url="http://127.0.0.1:11435/v1",
        local_allowed_ip="127.0.0.1", local_model="synthetic",
    )
    provider = Providers(cfg)
    revoked = False

    def boundary():
        if revoked:
            raise PermissionError("Synthetic revocation")

    provider.before_send = boundary

    async def scenario():
        nonlocal revoked
        waiting = asyncio.Event()
        provider.on_progress = lambda phase: waiting.set() if phase == "waiting_for_model" else None
        async with local_capacity(cfg):
            task = asyncio.create_task(getattr(provider, role)(
                [ContextPart(content="Synthetic", source_id="synthetic", revision=1)], ["user"]
            ))
            await asyncio.wait_for(waiting.wait(), 1)
            revoked = True
        with pytest.raises(PermissionError, match="Synthetic revocation"):
            await task

    asyncio.run(scenario())
    assert calls == []
    assert provider.before_send is boundary


def test_router_rechecks_existing_hook_before_second_schema_repair_request(monkeypatch, tmp_path):
    revoked = False

    def invalid_reply():
        nonlocal revoked
        revoked = True
        return {"invalid_schema": True}

    calls = transport(monkeypatch, invalid_reply)
    provider = Providers(Settings(
        source_dir=str(tmp_path), local_model="synthetic",
        local_base_url="http://127.0.0.1:11435/v1", local_allowed_ip="127.0.0.1"
    ))

    def boundary():
        if revoked:
            raise PermissionError("Synthetic repair revoked")

    provider.before_send = boundary
    with pytest.raises(PermissionError, match="repair revoked"):
        asyncio.run(provider.route(
            [ContextPart(content="Synthetic", source_id="synthetic", revision=1)], ["user"]
        ))
    assert len(calls) == provider.route_calls == 1


@pytest.mark.parametrize("action", [
    "delete", "message_revision", "message_content", "message_inactive", "manual", "archive",
    "provider_disabled", "provider_revision", "provider_deleted",
])
def test_title_source_or_provider_revocation_while_queued_sends_no_http(
    setup, monkeypatch, tmp_path, action
):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    pending(app, chat_id)
    with app.state.sessions() as db:
        binding = ProviderConfig(id="synthetic-local-title", name="Synthetic", kind="local",
                                 enabled=True, is_default=False, revision=1, config="{}")
        db.add(binding)
        db.commit()
        db.expunge(binding)
    calls = transport(monkeypatch)
    cfg = replace(
        app.state.settings, source_dir=str(tmp_path / "capacity"), local_model="synthetic",
        local_base_url="http://127.0.0.1:11435/v1", local_allowed_ip="127.0.0.1",
    )
    provider = Providers(cfg)
    prior_calls = []

    def prior():
        prior_calls.append(True)

    provider.before_send = prior

    async def scenario():
        waiting = asyncio.Event()
        provider.on_progress = lambda phase: waiting.set() if phase == "waiting_for_model" else None
        async with local_capacity(cfg):
            task = asyncio.create_task(execute_title(app.state.sessions, provider, chat_id,
                                                    provider_binding=binding))
            await asyncio.wait_for(waiting.wait(), 1)
            if action == "delete":
                response = client.delete("/api/conversations/" + chat_id, headers=headers)
                assert response.status_code == 200
            else:
                with app.state.sessions() as db:
                    chat = db.get(Conversation, chat_id)
                    message = db.scalar(select(Message).where(Message.conversation_id == chat_id))
                    actual = db.get(ProviderConfig, binding.id)
                    if action == "message_revision":
                        message.revision += 1
                    elif action == "message_content":
                        message.content = "Synthetic changed without revision"
                    elif action == "message_inactive":
                        message.active = False
                    elif action == "manual":
                        chat.manual_title, chat.title = True, "Synthetic manual title"
                    elif action == "archive":
                        chat.archived = True
                    elif action == "provider_disabled":
                        actual.enabled = False
                    elif action == "provider_revision":
                        actual.revision += 1
                    elif action == "provider_deleted":
                        db.delete(actual)
                    db.commit()
        await task

    asyncio.run(scenario())
    assert calls == [] and len(prior_calls) >= 2
    assert provider.before_send is prior
    with app.state.sessions() as db:
        chat = db.get(Conversation, chat_id)
        if chat:
            assert chat.title != "Synthetic generated title"


def test_title_valid_source_keeps_prior_hook_and_generates_once(setup, monkeypatch, tmp_path):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    pending(app, chat_id)
    calls = transport(monkeypatch)
    provider = Providers(replace(
        app.state.settings, source_dir=str(tmp_path), local_model="synthetic",
        local_base_url="http://127.0.0.1:11435/v1", local_allowed_ip="127.0.0.1",
    ))
    prior_calls = []
    def prior():
        prior_calls.append(True)
    provider.before_send = prior
    asyncio.run(execute_title(app.state.sessions, provider, chat_id))
    assert len(calls) == 1 and len(prior_calls) >= 3
    assert provider.before_send is prior
    with app.state.sessions() as db:
        assert db.get(Conversation, chat_id).title == "Synthetic generated title"
