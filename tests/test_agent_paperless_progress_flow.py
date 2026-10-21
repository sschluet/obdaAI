"""A known document goes through real typed dispatch before a follow-up can finish."""

import asyncio
import json
from uuid import uuid4

import pytest
from hub import agent_runtime as runtime
from hub.agent_models import AgentJob
from test_agent_private_read_flow import archive, decision, execute  # noqa: F401

pytest_plugins = ["test_agents", "test_agent_mail_read_flow"]


@pytest.mark.parametrize("invalid_first", [None, "stop", "ask", "finish", "wrong_document"])
def test_known_archive_document_is_read_without_permission_or_premature_stop(
    archive, monkeypatch, invalid_first  # noqa: F811
):
    case, start, scenario, calls = archive
    app, client, headers, cfg, identifier, chat, *_ = case
    first_id = start()
    first_turns = []

    async def search(*args):
        first_turns.append(True)
        if len(first_turns) == 1:
            return decision(identifier, operation="search", query="Synthetic contract")
        return {"kind": "finish", "message": "Document 42: Synthetic contract (bounded search)."}

    monkeypatch.setattr(runtime, "generate", search)
    assert execute(archive, first_id)["status"] == "observed"
    scenario["body"] = {
        "id": 42, "title": "Synthetic contract", "tags": [],
        "content": "Synthetic OCR: the permitted synthetic term is 30 days.",
    }
    response = client.post(
        f"/api/conversations/{chat}/agent-runs", headers=headers,
        json={
            "request_id": str(uuid4()),
            "goal": "Fasse den Inhalt des ersten Treffers aus deiner letzten Suche zusammen.",
            "research_allowed": True,
        },
    )
    assert response.status_code == 200, response.text
    followup_id = response.json()["id"]
    selections = []

    async def followup(*args):
        instruction, data = args[-2:]
        assert len(instruction.encode()) + len(runtime.encode(data).encode()) <= 14000
        assert data["allow_ask"] is False
        if not data["allow_finish"]:
            assert data["allow_stop"] is False
            candidate = json.loads(runtime.encode(data["ready_reads"]["decisions"][0]))
            assert candidate["integration_id"] == identifier
            assert candidate["tool"] == "paperless.read"
            assert candidate["arguments"]["operation"] == "document"
            assert candidate["arguments"]["document_id"] == 42
            selections.append(candidate)
            if len(selections) == 1 and invalid_first:
                if invalid_first == "wrong_document":
                    candidate["arguments"]["document_id"] = 43
                    return candidate
                return {"kind": invalid_first, "message": "Skip the known permitted read"}
            return candidate
        assert data["latest_observation"]["result"]["document_id"] == 42
        assert "30 days" in data["latest_observation"]["result"]["documents"][0]["content"]
        return {
            "kind": "finish",
            "message": "Document 42: Synthetic contract states 30 days (bounded OCR view).",
        }

    monkeypatch.setattr(runtime, "generate", followup)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, followup_id))
    with app.state.sessions() as db:
        job = db.get(AgentJob, followup_id)
        assert job.status == "observed", job.summary
        history = runtime.steps(db, followup_id)
        assert not any(s.kind in {"input", "effect", "research"} for s in history)
        assert sum(s.kind == "feedback" for s in history) == bool(invalid_first)
        assert len([s for s in history if s.kind == "read" and s.status == "succeeded"]) == 1
    assert len(calls) == 2
    assert calls[-1].url.path == "/api/documents/42/"
