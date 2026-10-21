"""Native archive citations survive model omissions without another read."""

import json

import pytest
from hub import agent_runtime as runtime
from hub.agent_models import AgentJob
from test_agent_private_read_flow import archive, decision, execute  # noqa: F401

pytest_plugins = ["test_agents", "test_agent_mail_read_flow"]


@pytest.mark.parametrize("filtered", [False, True])
def test_archive_completion_adds_current_read_sources_without_asking_or_rereading(
    archive, monkeypatch, filtered  # noqa: F811
):
    case, start, scenario, calls = archive
    app, _, _, _, identifier, *_ = case
    scenario["body"]["count"] = 37
    job_id = start()
    turns = []
    model_answer = "Die Abfrage zeigt einen begrenzten Ausschnitt."

    async def generate(*args):
        data = args[-1]
        assert len(args[-2].encode()) + len(runtime.encode(data).encode()) <= 14000
        turns.append(True)
        if len(turns) == 1:
            return decision(identifier, operation="search", query="Synthetic" if filtered else "")
        return {"kind": "finish", "message": model_answer}

    monkeypatch.setattr(runtime, "generate", generate)
    result = execute(archive, job_id)
    assert result["status"] == "observed"
    assert result["summary"].startswith(model_answer + "\n\n")
    assert "42" in result["summary"] and "37" in result["summary"]
    assert "Paperless" in result["summary"]
    assert len(calls) == 1 and len(turns) == 2
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert json.loads(job.bindings)["read_only"]
        assert not any(s.kind in {"input", "effect", "research"} for s in runtime.steps(db, job_id))


def test_archive_completion_cannot_claim_observed_when_current_sources_fail_validation(
    archive, monkeypatch  # noqa: F811
):
    from hub import agent_paperless_evidence

    case, start, _, calls = archive
    job_id = start()
    turns = []

    async def generate(*args):
        turns.append(True)
        if len(turns) == 1:
            return decision(case[4], operation="search")
        return {"kind": "finish", "message": "Unverified model text"}

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(agent_paperless_evidence, "paperless_evidence", lambda *args: None)
    result = execute(archive, job_id)
    assert result["status"] == "unverified"
    assert "Unverified model text" not in result["summary"]
    assert len(calls) == 1 and len(turns) == 2
