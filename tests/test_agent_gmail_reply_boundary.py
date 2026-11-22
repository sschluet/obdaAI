"""An ID-only Gmail search must never become invented reply-status evidence."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from hub import agent_runtime as runtime
from hub.agent_intent import RequestIntent, Requirement
from hub.agent_models import AgentPolicy
from hub.agent_tools import Rules
from hub.gmail_client import API_BASE
from hub.integrations import Integration
from test_actions import gateway, set_pause  # noqa: F401
from test_agents import agent  # noqa: F401
from test_integration_writes import writes  # noqa: F401


@pytest.mark.parametrize(("data", "queried"), [
    ({"messages": [{"id": "abc", "threadId": "def"}]}, False),
    ({"messages": []}, True),
    ({"messages": [], "nextPageToken": "more"}, False),
    ({}, False),
])
def test_gmail_id_search_does_not_prove_message_content(data, queried):
    step = SimpleNamespace(
        kind="read", status="succeeded",
        document=json.dumps({"tool": "gmail.read", "arguments": {"operation": "search"}}),
        result=json.dumps({"label": "LOCAL_ONLY", "operation": "search", "data": data}),
    )
    assert runtime.mailbox_queried([step]) is queried


@pytest.mark.parametrize("goal", [
    "Auf welche Mails habe ich bereits geantwortet?",
    "Welche davon sind beantwortet?",
    "Which emails have I replied to?",
    "Show the reply status of these messages",
])
def test_native_gmail_reply_gap_is_explicit_before_unproven_model_finish(
    agent, monkeypatch, goal  # noqa: F811
):
    app, client, headers, cfg, identifier, chat, *_ = agent
    monkeypatch.setattr("hub.gmail_setup.read_ready", lambda *args: True)
    with app.state.sessions() as db:
        profile = db.get(Integration, identifier)
        profile.kind, profile.name, profile.writes_enabled = "gmail", "Synthetic Gmail", False
        profile.config = json.dumps({"kind": "gmail", "url": API_BASE, "auth": "oauth"})
        policy = db.get(AgentPolicy, identifier)
        policy.rules = Rules(enabled=True, gmail_read=True, max_effects=0).model_dump_json()
        db.commit()

    def no_target(*args, **kwargs):
        raise AssertionError("No Gmail request can prove a missing implemented reply contract")

    async def no_model(*args, **kwargs):
        if args[-1].get("intent_schema"):
            return RequestIntent(
                target_ids=[identifier], mode="observe", topic="mail", origin="semantic",
                requirements=[Requirement(kind="mail_reply", integration_id=identifier)],
            ).model_dump()
        raise AssertionError("An ID search or model claim cannot establish reply evidence")

    monkeypatch.setattr(runtime, "invoke", no_target)
    monkeypatch.setattr(runtime, "generate", no_model)
    monkeypatch.setattr(runtime, "research", no_model)
    response = client.post(
        f"/api/conversations/{chat}/agent-runs",
        json={"request_id": str(uuid4()), "goal": goal}, headers=headers,
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    result = client.get("/api/agent-runs/" + job_id).json()
    assert result["status"] == "unverified"
    assert "Gmail" in result["summary"] and "nicht verlässlich" in result["summary"]
    assert not result["steps"]
