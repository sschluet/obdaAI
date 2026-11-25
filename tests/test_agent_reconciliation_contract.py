"""Reconciliation binds private original goals and current source targets, never writes."""

import asyncio
import json
from uuid import uuid4

import pytest
from hub import agent_runtime as runtime
from hub.agent_models import AgentJob, AgentPolicy
from hub.integrations import Integration, IntegrationBinding
from hub.provider_settings import encrypt
from test_agents import effect, start

pytest_plugins = ["test_agents"]
GOAL = (
    "Prüfe ausschließlich lesend den tatsächlichen Zustand nach dem unklaren Auftrag. "
    "Keine Änderung wiederholen."
)


def previous(agent, *, goal=None, second=False):
    app, client, headers, cfg, identifier, chat, *_ = agent
    ids = [identifier]
    if second:
        with app.state.sessions() as db:
            original = db.get(Integration, identifier)
            profile = Integration(
                name="Second synthetic target",
                kind=original.kind,
                enabled=True,
                writes_enabled=True,
                config=original.config,
            )
            db.add(profile)
            db.flush()
            profile.encrypted_secret = encrypt(
                cfg, "integration:" + profile.id, "synthetic-write-token"
            )
            db.add(
                AgentPolicy(
                    integration_id=profile.id,
                    profile_revision=profile.revision,
                    rules=db.get(AgentPolicy, identifier).rules,
                )
            )
            ids.append(profile.id)
            db.commit()
        response = client.put(
            "/api/integration-bindings/conversation/" + chat,
            headers=headers,
            json={"expected_revision": 1, "integration_ids": ids, "selection_mode": "manual"},
        )
        assert response.status_code == 200, response.text
    job_id = start(agent)
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        if goal is not None:
            job.goal = goal
        for identifier in ids:
            decision = {**effect(agent), "integration_id": identifier}
            step = runtime.record(db, job, "effect", decision)
            step.status = "uncertain"
            step.result = json.dumps({"effect_verified": False})
        job.status = "uncertain"
        db.commit()
    return job_id, ids


def request(agent, source, **updates):
    return agent[1].post(
        "/api/conversations/" + agent[5] + "/agent-runs",
        headers=agent[2],
        json={
            "request_id": str(uuid4()),
            "goal": GOAL,
            "read_only": True,
            "research_allowed": False,
            "reconcile_job_id": source,
            **updates,
        },
    )


def test_long_original_goal_is_private_full_context_and_server_scoped_observe(agent):
    original = "Synthetic original goal: " + "x" * (8000 - len("Synthetic original goal: "))
    source, ids = previous(agent, goal=original)
    response = request(agent, source)
    assert response.status_code == 200, response.text
    with agent[0].state.sessions() as db:
        job = db.get(AgentJob, response.json()["id"])
        parts = json.loads(job.context)
        source_goal = next(p for p in parts if p["source_id"] == "agent-effect:" + source + ":goal")
        assert source_goal["content"].endswith(original)
        assert source_goal["label"] == "LOCAL_ONLY"
        bindings = json.loads(job.bindings)
        assert job.goal == GOAL and job.max_effects == 0 and not job.research_allowed
        assert bindings["read_only"] is True
        assert bindings["intent"]["mode"] == "observe" and bindings["intent"]["target_ids"] == ids
        assert bindings["reconciliation"]["job_id"] == source
        assert len(bindings["reconciliation"]["steps"]) == 1
        assert db.get(AgentJob, source).goal == original


@pytest.mark.parametrize(
    "change", ["selection", "profile", "policy", "disabled", "research", "write"]
)
def test_reconciliation_rejects_revoked_source_and_nonread_requests(agent, change):
    source, _ = previous(agent)
    with agent[0].state.sessions() as db:
        if change == "selection":
            db.get(IntegrationBinding, ("conversation", agent[5])).integration_ids = "[]"
        elif change == "profile":
            db.get(Integration, agent[4]).revision += 1
        elif change == "policy":
            db.get(AgentPolicy, agent[4]).revision += 1
        elif change == "disabled":
            db.get(Integration, agent[4]).enabled = False
        db.commit()
    update = (
        {"research_allowed": True}
        if change == "research"
        else {"read_only": False}
        if change == "write"
        else {}
    )
    assert request(agent, source, **update).status_code == 409


@pytest.mark.parametrize("selected", ["both", "subset", "unrelated", "removed"])
def test_multiple_uncertain_source_targets_are_exact_not_user_expanded(agent, selected):
    source, ids = previous(agent, second=True)
    if selected == "removed":
        with agent[0].state.sessions() as db:
            db.get(IntegrationBinding, ("conversation", agent[5])).integration_ids = json.dumps(
                ids[:1]
            )
            db.commit()
    chosen = (
        ids
        if selected in {"both", "removed"}
        else ids[:1]
        if selected == "subset"
        else [str(uuid4())]
    )
    response = request(agent, source, integration_ids=chosen)
    assert response.status_code == (200 if selected == "both" else 409), response.text
    if selected == "both":
        with agent[0].state.sessions() as db:
            frozen = json.loads(db.get(AgentJob, response.json()["id"]).bindings)
            assert set(frozen["intent"]["target_ids"]) == set(ids)
            assert {p["id"] for p in frozen["profiles"]} == set(ids)


@pytest.mark.parametrize("write", [False, True])
def test_reconciliation_executes_general_read_path_but_never_replays_effect(
    agent, monkeypatch, write
):
    source, _ = previous(agent)
    response = request(agent, source)
    assert response.status_code == 200, response.text
    read = {
        "kind": "tool",
        "integration_id": agent[4],
        "tool": "http",
        "arguments": {"method": "GET", "path": "/api/documents/1/"},
        "message": "Read state",
    }
    choices = iter(
        [effect(agent) if write else read, {"kind": "finish", "message": "Observed state"}]
    )
    invoked = []

    async def generate(*args):
        return next(choices)

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        invoked.append(args)
        assert args["method"] == "GET"
        return {"http_status": 200, "body": dict(agent[6]), "effect_verified": False}

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", invoke)
    asyncio.run(
        runtime.execute_agent(agent[0].state.sessions, agent[3], None, response.json()["id"])
    )
    result = agent[1].get("/api/agent-runs/" + response.json()["id"]).json()
    assert not agent[7]
    assert not any(s["kind"] == "effect" for s in result["steps"])
    if not write:
        assert result["status"] == "observed" and len(invoked) == 1
    else:
        assert result["status"] in {"failed", "unverified"} and not invoked


def test_reconciliation_request_id_replays_only_same_original_source(agent):
    source, _ = previous(agent)
    request_id = str(uuid4())
    first = request(agent, source, request_id=request_id)
    assert first.status_code == 200, first.text
    replay = request(agent, source, request_id=request_id)
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    assert request(agent, str(uuid4()), request_id=request_id).status_code == 409
    with agent[0].state.sessions() as db:
        original = db.get(AgentJob, source)
        original.goal += " Changed synthetic source"
        db.commit()
    assert request(agent, source, request_id=request_id).status_code == 409


def test_reconciliation_final_gate_rechecks_policy_after_creation(agent, monkeypatch):
    source, _ = previous(agent)
    response = request(agent, source)
    assert response.status_code == 200, response.text
    with agent[0].state.sessions() as db:
        db.get(AgentPolicy, agent[4]).revision += 1
        db.commit()

    async def forbidden(*args):
        raise AssertionError("Revoked reconciliation must not reach model planning")

    monkeypatch.setattr(runtime, "generate", forbidden)
    monkeypatch.setattr(runtime, "invoke", forbidden)
    asyncio.run(
        runtime.execute_agent(
            agent[0].state.sessions,
            agent[3],
            None,
            response.json()["id"],
        )
    )
    result = agent[1].get("/api/agent-runs/" + response.json()["id"]).json()
    assert result["status"] == "failed"
    assert not any(step["kind"] in {"read", "effect"} for step in result["steps"])
