"""An actually displayed empty mail cohort needs no new mailbox/model access."""

import asyncio
import json
from uuid import uuid4

import pytest
from hub import agent_runtime as runtime
from hub.agent_models import AgentJob, AgentPolicy
from hub.mcp_client import schema_digest

pytest_plugins = ["test_agent_mail_read_flow"]

SEARCH = {"type": "object", "properties": {
    "query": {"type": "string"}, "since_days": {"type": "integer"},
}, "additionalProperties": False}
SCENARIO = {
    "goal": "Was gab es heute für neue Mails?", "clock_at": "2026-10-21T10:00:00+02:00",
    "schemas": {"search_emails": SEARCH},
    "query_payload": {"folder": "INBOX", "messages": [
        {"uid": i, "folder": "INBOX", "message_id": f"<old-{i}@synthetic.invalid>",
         "subject": f"Synthetic prior-day mail {i}", "received": "2026-10-20T09:00:00+02:00"}
        for i in range(1, 7)
    ]},
}


@pytest.mark.parametrize("read_mailbox", [SCENARIO], indirect=True)
@pytest.mark.parametrize("change", [None, "revoke", "cancel", "pending_effect"])
def test_empty_display_reply_followup_has_no_new_steps_model_or_mailbox_calls(
    read_mailbox, monkeypatch, change,
):
    app, client, headers, cfg, identifier, first_id, calls = read_mailbox
    turns = []

    async def first_model(*args):
        turns.append(True)
        if len(turns) == 1:
            return {"kind": "tool", "tool": "mcp.call", "integration_id": identifier,
                    "arguments": {"name": "search_emails", "schema_sha256": schema_digest(SEARCH),
                                  "arguments": {"query": "", "since_days": 0}},
                    "message": "Read current synthetic mailbox headers"}
        return {"kind": "finish", "message": "Native overview must replace this model text"}

    monkeypatch.setattr(runtime, "generate", first_model)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, first_id))
    with app.state.sessions() as db:
        first = db.get(AgentJob, first_id)
        assert first.status == "observed" and "0" in first.summary
        chat = first.conversation_id
    previous_calls = len(calls)
    created = client.post(
        f"/api/conversations/{chat}/agent-runs", headers=headers,
        json={"request_id": str(uuid4()), "goal": "Welche davon habe ich bereits beantwortet?"},
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["id"]
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert any(part["source_id"].startswith("agent-read:")
                   for part in json.loads(job.context))
        if change == "revoke":
            db.get(AgentPolicy, identifier).revision += 1
        elif change == "cancel":
            job.cancel_requested = True
        elif change == "pending_effect":
            effect = runtime.record(db, job, "effect", {"integration_id": identifier,
                                                        "tool": "mcp.call", "arguments": {}})
            effect.status = "dispatching"
        db.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("No further model/research for a source-bound empty selection")

    def no_transport(*args, **kwargs):
        pytest.fail("No current catalog/Inbox/Sent read is needed for the empty selection")

    monkeypatch.setattr(runtime, "generate", forbidden)
    monkeypatch.setattr(runtime, "research", forbidden)
    monkeypatch.setattr(runtime, "invoke", no_transport)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    result = client.get("/api/agent-runs/" + job_id).json()
    assert len(calls) == previous_calls
    if change is None:
        assert result["status"] == "observed" and result["steps"] == []
        assert "0 Mails" in result["summary"]
        assert "Gesendet-Ordner wurde dafür nicht geprüft" in result["summary"]
        assert "keine Aussage" in result["summary"]
    else:
        assert result["status"] == {"revoke": "failed", "cancel": "cancelled",
                                    "pending_effect": "uncertain"}[change]
        assert "0 Mails" not in result["summary"]
