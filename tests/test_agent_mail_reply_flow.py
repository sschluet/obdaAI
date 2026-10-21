"""Actual shared dispatch with synthetic receipts and a source-bound status answer."""

import asyncio
import json
from uuid import uuid4

import pytest
from hub import agent_runtime as runtime
from hub.agent_models import AgentJob
from hub.mcp_client import schema_digest

pytest_plugins = ["test_agent_mail_read_flow"]

SEARCH = {
    "type": "object",
    "properties": {"query": {"type": "string"}, "since_days": {"type": "integer"}},
    "additionalProperties": False,
}
LIST = {
    "type": "object",
    "properties": {"folder": {"type": "string"}, "limit": {"type": "integer", "maximum": 100}},
    "required": ["folder", "limit"],
    "additionalProperties": False,
}
SCENARIO = {
    "goal": "Was gab es heute für neue Mails?",
    "clock_at": "2026-10-21T10:00:00+02:00",
    "schemas": {
        "search_emails": SEARCH,
        "list_folders": {"type": "object", "properties": {}, "additionalProperties": False},
        "list_emails": LIST,
    },
    "folders": [{"name": "Actual Sent", "selectable": True, "flags": ["\\Sent"]}],
    "query_payload": {
        "folder": "INBOX",
        "messages": [
            {
                "uid": number,
                "folder": "INBOX",
                "message_id": f"<original-{number}@synthetic.invalid>",
                "subject": f"Synthetic mail {number}",
                "received": "2026-10-21T09:00:00+02:00",
                "answered": number == 1,
            }
            for number in (1, 2)
        ],
    },
}


@pytest.mark.parametrize("read_mailbox", [SCENARIO], indirect=True)
@pytest.mark.parametrize("linked,cancel", [(False, False), (True, False), (True, True)])
def test_reply_status_completes_from_current_sent_headers_without_model_prose(
    read_mailbox, monkeypatch, linked, cancel
):
    app, client, headers, cfg, identifier, first_id, calls = read_mailbox
    initial_turns = []

    async def initial(*args):
        initial_turns.append(True)
        if len(initial_turns) == 1:
            return {
                "kind": "tool", "integration_id": identifier, "tool": "mcp.call",
                "arguments": {
                    "name": "search_emails", "schema_sha256": schema_digest(SEARCH),
                    "arguments": {"query": "", "since_days": 0},
                },
                "message": "Read actual synthetic headers",
            }
        return {"kind": "finish", "message": "Replaced by bound overview evidence"}

    async def no_research(*args):
        pytest.fail("Private mailbox data must not initiate public research")

    monkeypatch.setattr(runtime, "research", no_research)
    monkeypatch.setattr(runtime, "generate", initial)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, first_id))
    with app.state.sessions() as db:
        first = db.get(AgentJob, first_id)
        assert first.status == "observed"
        chat = first.conversation_id
    started = client.post(
        f"/api/conversations/{chat}/agent-runs", headers=headers,
        json={
            "request_id": str(uuid4()), "goal": "Welche davon habe ich bereits beantwortet?",
            "research_allowed": True,
        },
    )
    assert started.status_code == 200, started.text
    followup_id = started.json()["id"]
    selections = []
    original_payload = SCENARIO["query_payload"]

    async def select_read(*args):
        data = args[-1]
        assert data["allow_finish"] is False
        assert data["allow_ask"] is False
        candidate = json.loads(runtime.encode(data["ready_reads"]["decisions"][0]))
        name = candidate["arguments"]["name"]
        selections.append(name)
        if len(selections) == 1:
            assert name == "list_folders"
        elif len(selections) == 2:
            assert name == "list_emails"
            assert candidate["arguments"]["arguments"] == {"folder": "Actual Sent", "limit": 20}
            SCENARIO.update(
                expected_query_tool=name,
                expected_query_arguments={"folder": "Actual Sent", "limit": 20},
                query_payload={
                    "folder": "Actual Sent",
                    "messages": [{
                        "uid": 9, "folder": "Actual Sent",
                        "message_id": "<reply@synthetic.invalid>",
                        "in_reply_to": "<original-2@synthetic.invalid>",
                    }] if linked else [],
                },
            )
        else:
            pytest.fail("Verified reply facts must not be rewritten by another model turn")
        return candidate

    monkeypatch.setattr(runtime, "generate", select_read)
    original_dispatch = runtime.dispatch

    def dispatch_then_cancel(factory, settings, job_id, sequence):
        original_dispatch(factory, settings, job_id, sequence)
        if cancel and job_id == followup_id:
            with factory() as db:
                step = next(s for s in runtime.steps(db, job_id) if s.sequence == sequence)
                if json.loads(step.document).get("arguments", {}).get("name") == "list_emails":
                    assert step.status == "succeeded"
                    db.get(AgentJob, job_id).cancel_requested = True
                    db.commit()

    monkeypatch.setattr(runtime, "dispatch", dispatch_then_cancel)
    try:
        asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, followup_id))
        with app.state.sessions() as db:
            job = db.get(AgentJob, followup_id)
            if cancel:
                assert job.status == "cancelled"
                assert "als beantwortet markiert" not in job.summary
            else:
                assert job.status == "observed", job.summary
                assert "2" in job.summary and "1 als beantwortet markiert" in job.summary
                assert "Eintrag 1" in job.summary and "Eintrag 2" in job.summary
                assert "unbekannt" in job.summary and "nicht vollständig" in job.summary
            assert not any(
                s.kind in {"input", "effect", "research"}
                for s in runtime.steps(db, followup_id)
            )
        assert selections == ["list_folders", "list_emails"]
        assert [c["params"]["name"] for c in calls if c["method"] == "tools/call"] == [
            "search_emails", "list_folders", "list_emails",
        ]
    finally:
        SCENARIO["query_payload"] = original_payload
        SCENARIO.pop("expected_query_tool", None)
        SCENARIO.pop("expected_query_arguments", None)
