"""Polling exposes real model/operation phases without reading target payloads."""

import json

from hub import agent_runtime as runtime
from hub.agent_models import AgentJob, AgentStep
from hub.db import Run
from test_agent_capability_runtime import start

pytest_plugins = ["test_agent_capability_runtime"]


def test_progress_reports_queue_then_actual_model_status_across_polls(ha):
    app, client, _, _, _, chat, *_ = ha
    identifier = start(ha, "Welche Updates stehen in Home Assistant aus?", research_allowed=False)
    queued = client.get("/api/agent-runs/" + identifier).json()["activity"]
    assert queued["phase"] == "queued" and queued["can_cancel"]
    with app.state.sessions() as db:
        job = db.get(AgentJob, identifier)
        job.status = "running"
        run = Run(conversation_id=job.model_conversation_id, status="queued")
        db.add(run)
        db.flush()
        item = runtime.record(db, job, "model", {
            "intent_interpretation": True, "reasoning": "PRIVATE_MODEL_REASONING",
        })
        item.model_run_id, item.status = run.id, "dispatching"
        run_id = run.id
        db.commit()
    first = client.get("/api/agent-runs", params={"conversation_id": chat}).json()[0]
    assert first["activity"]["phase"] == "planning"
    assert "Wartet" in first["activity"]["waiting_reason"]
    assert "PRIVATE_MODEL_REASONING" not in json.dumps(first["activity"])
    with app.state.sessions() as db:
        db.get(Run, run_id).status = "streaming"
        db.commit()
    second = client.get("/api/agent-runs/" + identifier).json()
    assert "verarbeitet" in second["activity"]["waiting_reason"]
    assert first["activity"]["event_key"] != second["activity"]["event_key"]


def test_compact_progress_never_parses_opaque_receipts_and_needs_authentication(ha):
    app, client, _, _, _, chat, *_ = ha
    identifier = start(ha, "Welche Lampen gibt es?", research_allowed=False)
    with app.state.sessions() as db:
        owner = db.get(AgentJob, identifier)
        owner.status = "running"
        item = runtime.record(db, owner, "read", {"message": "PRIVATE_REMOTE_PROSE"})
        item.status = "dispatching"
        item.result = "opaque-not-decoded-for-progress"
        db.commit()
    response = client.get("/api/agent-runs", params={"conversation_id": chat})
    assert response.status_code == 200
    result = response.json()[0]
    assert result["activity"]["phase"] == "reading"
    assert result["steps"][0]["result"] == {}
    assert "PRIVATE_REMOTE_PROSE" not in json.dumps(result["activity"])
    with app.state.sessions() as db:
        assert db.get(AgentStep, (identifier, 1)).result == "opaque-not-decoded-for-progress"
    client.cookies.clear()
    assert client.get("/api/agent-runs", params={"conversation_id": chat}).status_code == 401
