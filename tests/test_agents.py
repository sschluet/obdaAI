"""Authority, replay, verification and shared entry-point acceptance for agents."""

import asyncio
import json
from uuid import uuid4

import pytest
from hub import agent_api
from hub import agent_runtime as runtime
from hub.agent_models import AgentJob, AgentPolicy
from hub.agent_tools import Rules, validate_tool
from hub.db import ActionPolicy
from test_actions import gateway, set_pause  # noqa: F401
from test_integration_writes import writes  # noqa: F401


@pytest.fixture
def agent(writes, monkeypatch):  # noqa: F811
    app, client, headers, cfg, integration_id, state, effects = writes
    monkeypatch.setattr(agent_api, "start_development_agent", lambda *a: None)
    chat = client.post("/api/conversations", json={}, headers=headers).json()["id"]
    response = client.put(
        "/api/integration-bindings/conversation/" + chat,
        json={
            "expected_revision": 0,
            "integration_ids": [integration_id],
            "selection_mode": "manual",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    rules = Rules(
        enabled=True,
        autonomous=True,
        http_prefixes=["/api/"],
        http_methods=["GET", "PATCH"],
        max_steps=8,
        max_effects=2,
    )
    response = client.put(
        "/api/integrations/" + integration_id + "/agent-policy",
        json={
            "expected_revision": 0,
            "expected_profile_revision": 1,
            "rules": rules.model_dump(),
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert set_pause(client, headers, False).status_code == 200
    return app, client, headers, cfg, integration_id, chat, state, effects


def start(agent):
    app, client, headers, cfg, integration_id, chat, state, effects = agent
    response = client.post(
        "/api/conversations/" + chat + "/agent-runs",
        json={
            "request_id": str(uuid4()),
            "goal": "Rename the synthetic document to After",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def run(agent, job_id, monkeypatch, decisions):
    app, client, headers, cfg, integration_id, chat, state, effects = agent
    replies = iter(decisions)

    async def generate(*args):
        return next(replies)

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        assert secret == "synthetic-write-token"
        if args["method"] == "PATCH":
            effects.append(args)
            state["title"] = args["body"]["title"]
        return {
            "body": dict(state),
            "effect_verified": False,
            "verification_passed": state["title"] == "After",
        }

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", invoke)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    return client.get("/api/agent-runs/" + job_id).json()


def effect(agent):
    return {
        "kind": "tool",
        "message": "Rename",
        "integration_id": agent[4],
        "tool": "http",
        "arguments": {"method": "PATCH", "path": "/api/documents/1/", "body": {"title": "After"}},
    }


def test_agent_executes_and_requires_independent_verification(agent, monkeypatch):
    job_id = start(agent)
    # The stub has no model steps. The first actual effect is therefore sequence 1.
    verify = {
        "kind": "tool",
        "message": "Check title",
        "integration_id": agent[4],
        "tool": "http.verify",
        "arguments": {
            "path": "/api/documents/1/",
            "effect_step": 1,
            "expected": {"/body/title": "After"},
        },
    }
    result = run(
        agent,
        job_id,
        monkeypatch,
        [effect(agent), verify, {"kind": "finish", "message": "Title checked"}],
    )
    assert result["status"] == "succeeded", json.dumps(result, indent=2)
    assert len(agent[-1]) == 1
    assert result["steps"][0]["result"]["effect_verified"] is True
    run(agent, job_id, monkeypatch, [])
    assert len(agent[-1]) == 1


def test_model_claim_cannot_turn_acknowledgment_into_verified_success(agent, monkeypatch):
    result = run(
        agent,
        start(agent),
        monkeypatch,
        [effect(agent), {"kind": "finish", "message": "All finished"}],
    )
    assert result["status"] == "unverified"
    assert "nicht vollständig" in result["summary"]


@pytest.mark.parametrize("change", ["pause", "policy", "profile", "selection", "cancel", "budget"])
def test_final_gate_reloads_authority_after_transport_setup(agent, monkeypatch, change):
    app, client, headers, cfg, integration_id, chat, state, effects = agent
    job_id = start(agent)

    async def generate(*a):
        return effect(agent)

    def setup_then_send(cfg, config, secret, tool, args, rules, before_send):
        with app.state.sessions() as db:
            if change == "pause":
                db.get(ActionPolicy, 1).paused = True
            elif change == "policy":
                db.get(AgentPolicy, integration_id).revision += 1
            elif change == "profile":
                from hub.integrations import Integration

                db.get(Integration, integration_id).writes_enabled = False
            elif change == "selection":
                from hub.integrations import IntegrationBinding

                db.get(IntegrationBinding, ("conversation", chat)).revision += 1
            elif change == "cancel":
                db.get(AgentJob, job_id).cancel_requested = True
            else:
                db.get(AgentJob, job_id).created = 0
            db.commit()
        before_send()
        effects.append("MUST NOT SEND")

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", setup_then_send)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    result = client.get("/api/agent-runs/" + job_id).json()
    assert not effects
    assert result["status"] == "uncertain"
    assert result["steps"][0]["status"] == "uncertain"


def test_lost_response_is_not_replayed(agent, monkeypatch):
    job_id = start(agent)
    app, client, headers, cfg, integration_id, chat, state, effects = agent

    async def generate(*a):
        return effect(agent)

    def lost(*args):
        args[-1]()
        effects.append("applied")
        raise TimeoutError("synthetic lost response")

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", lost)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    assert effects == ["applied"]
    assert client.get("/api/agent-runs/" + job_id).json()["status"] == "uncertain"


def test_restart_with_persisted_intent_never_resends(agent, monkeypatch):
    job_id = start(agent)
    app, client, headers, cfg, integration_id, chat, state, effects = agent
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        runtime.record(db, job, "effect", effect(agent)).status = "dispatching"
        job.status = "running"
        db.commit()
    result = run(agent, job_id, monkeypatch, [])
    assert result["status"] == "uncertain"
    assert not effects


def test_manual_approval_is_bound_to_exact_step(agent, monkeypatch):
    app, client, headers, cfg, integration_id, chat, state, effects = agent
    with app.state.sessions() as db:
        row = db.get(AgentPolicy, integration_id)
        rules = json.loads(row.rules)
        rules["autonomous"] = False
        row.rules = json.dumps(rules)
        db.commit()
    job_id = start(agent)
    result = run(agent, job_id, monkeypatch, [effect(agent)])
    assert result["status"] == "awaiting_approval"
    assert not effects
    step = result["steps"][0]
    wrong = client.post(
        "/api/agent-runs/" + job_id + "/approve",
        json={
            "sequence": step["sequence"],
            "sha256": "a" * 64,
        },
        headers=headers,
    )
    assert wrong.status_code == 409
    accepted = client.post(
        "/api/agent-runs/" + job_id + "/approve",
        json={
            "sequence": step["sequence"],
            "sha256": step["sha256"],
        },
        headers=headers,
    )
    assert accepted.status_code == 200
    result = run(agent, job_id, monkeypatch, [{"kind": "finish", "message": "Applied"}])
    assert len(effects) == 1
    assert result["status"] == "unverified"


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.test/api/",
        "//evil.test/api/",
        "/api/../admin/",
        "/api/%2e%2e/admin",
        "/api/x?url=https://evil.test",
        "/api/x\\y",
    ],
)
def test_model_paths_cannot_replace_target_or_escape_prefix(path):
    with pytest.raises((ValueError, PermissionError)):
        validate_tool(
            "home_assistant", Rules(enabled=True, http_prefixes=["/api/"]), "http", {"path": path}
        )


def test_mcp_annotations_cannot_confer_read_authority():
    _, effective = validate_tool(
        "mcp",
        Rules(enabled=True, mcp=True),
        "mcp.call",
        {
            "name": "read_only_claim",
            "schema_sha256": "a" * 64,
            "arguments": {},
        },
    )
    assert effective is True


def test_missing_rules_never_inherit_bounded_write_permission(writes, monkeypatch):  # noqa: F811
    app, client, headers, cfg, integration_id, state, effects = writes
    response = client.get("/api/integrations/" + integration_id + "/agent-policy")
    assert response.json()["rules"]["enabled"] is False


def test_task_can_select_shared_agent_but_not_hide_it_in_read_only_profile():
    from hub.task_api import TaskSpec

    spec = {
        "title": "Administer",
        "goal": "Inspect and maintain selected systems",
        "steps": [{"tool_id": "agent.run", "parameters": {"research_allowed": True}}],
        "autonomy": "bounded_autonomous",
        "success_criterion": "all_steps_completed",
        "timeout_seconds": 600,
    }
    assert TaskSpec.model_validate(spec).steps[0].tool_id == "agent.run"
    with pytest.raises(ValueError):
        TaskSpec.model_validate({**spec, "autonomy": "analyze_only"})


def test_empty_model_claim_is_not_system_acceptance(agent, monkeypatch):
    result = run(agent, start(agent), monkeypatch, [{"kind": "finish", "message": "Updated"}])
    assert result["status"] == "unverified"
    assert not agent[-1]


def test_public_research_planner_receives_no_private_observations(agent, monkeypatch):
    import hub.websearch as web

    app, client, headers, cfg, integration_id, chat, state, effects = agent
    job_id = start(agent)
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        job.research_allowed = True
        job.context = json.dumps(
            [
                {
                    "source_id": "private",
                    "revision": 1,
                    "content": "PRIVATE-SOURCE-MUST-NOT-BE-SEARCHED",
                }
            ]
        )
        runtime.record(db, job, "read", {"message": "Private state"}).result = json.dumps(
            {
                "config": "PRIVATE-CONFIG-MUST-NOT-BE-SEARCHED",
            }
        )
        db.commit()
    queries = []

    async def public_plan(*args):
        data = json.dumps(args[-1])
        assert "PRIVATE-" not in data
        assert set(args[-1]) == {"current_user_request", "topic", "previous_public_sources"}
        return {"queries": ["official paperless API documentation"]}

    async def search(cfg, request, **kwargs):
        queries.append(request.query)
        return []

    monkeypatch.setattr(runtime, "generate", public_plan)
    monkeypatch.setattr(web, "search", search)
    asyncio.run(runtime.research(app.state.sessions, cfg, None, job_id))
    assert queries == ["official paperless API documentation"]


def test_task_dispatch_uses_shared_loop_and_confirm_each_overrides_profile(agent, monkeypatch):
    import hub.task_model as task_model
    from hub.agent_tasks import execute_agent_task
    from hub.db import TaskRun
    from sqlalchemy import select

    app, client, headers, cfg, integration_id, chat, state, effects = agent

    async def no_background(*args):
        pass

    monkeypatch.setattr(task_model, "execute_task", no_background)
    spec = {
        "title": "Synthetic agent task",
        "goal": "Rename the synthetic document",
        "steps": [{"tool_id": "agent.run"}],
        "autonomy": "confirm_each",
        "success_criterion": "all_steps_completed",
        "timeout_seconds": 600,
    }
    response = client.post("/api/tasks", json=spec, headers=headers)
    assert response.status_code == 200, response.text
    task = response.json()
    selected = client.put(
        "/api/integration-bindings/task/" + task["id"],
        json={
            "expected_revision": 0,
            "integration_ids": [integration_id],
            "selection_mode": "manual",
        },
        headers=headers,
    )
    assert selected.status_code == 200, selected.text
    task = client.patch(
        "/api/tasks/" + task["id"] + "/control",
        json={
            "expected_revision": task["revision"],
            "expected_control_revision": task["control_revision"],
            "paused": False,
        },
        headers=headers,
    ).json()
    started = client.post(
        "/api/tasks/" + task["id"] + "/runs",
        json={
            "request_id": str(uuid4()),
            "expected_revision": task["revision"],
            "expected_control_revision": task["control_revision"],
            "spec_sha256": task["spec_sha256"],
        },
        headers=headers,
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["id"]

    async def generate(*args):
        return effect(agent)

    monkeypatch.setattr(runtime, "generate", generate)
    asyncio.run(execute_agent_task(app.state.sessions, cfg, run_id))
    with app.state.sessions() as db:
        job = db.scalar(select(AgentJob).where(AgentJob.task_run_id == run_id))
        assert job.status == "awaiting_approval"
        assert db.get(TaskRun, run_id).status == "awaiting_approval"
        assert json.loads(job.bindings)["autonomy_allowed"] is False
    assert not effects
    cancelled = client.post("/api/task-runs/" + run_id + "/cancel", json={}, headers=headers)
    assert cancelled.status_code == 200
    assert client.get("/api/agent-runs/" + job.id).json()["status"] == "cancelled"


def test_prebound_predicate_reconciles_lost_response_without_mutation_retry(agent, monkeypatch):
    from hub import agent_reconcile

    job_id = start(agent)
    decisions = iter([effect(agent), {"kind": "finish", "message": "State checked"}])
    first = next(decisions)
    first["arguments"]["verification"] = {
        "path": "/api/documents/1/",
        "expected": {"/title": "After"},
        "timeout_seconds": 2,
        "interval_seconds": 1,
    }
    decisions = iter([first, next(decisions)])
    mutations, observations = [], []

    async def generate(*args):
        return next(decisions)

    def lost(cfg, config, secret, tool, args, rules, boundary):
        boundary()
        mutations.append(args)
        agent[6]["title"] = "After"
        raise TimeoutError("response lost after effect")

    def observe(cfg, config, secret, tool, args, rules, boundary):
        boundary()
        observations.append(args)
        assert tool == "http.verify" and args["method"] == "GET"
        return {"verification_passed": agent[6]["title"] == "After"}

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", lost)
    monkeypatch.setattr(agent_reconcile, "invoke", observe)
    asyncio.run(runtime.execute_agent(agent[0].state.sessions, agent[3], None, job_id))
    result = agent[1].get("/api/agent-runs/" + job_id).json()
    assert result["status"] == "succeeded"
    receipt = next(s["result"] for s in result["steps"] if s["kind"] == "effect")
    assert receipt["effect_verified"] and receipt["reconciled_after_uncertain"]
    assert len(mutations) == len(observations) == 1


def test_read_only_job_rejects_model_mutation_at_dispatch(agent, monkeypatch):
    response = agent[1].post(
        "/api/conversations/" + agent[5] + "/agent-runs",
        json={"request_id": str(uuid4()), "goal": "Read state only", "read_only": True},
        headers=agent[2],
    )
    assert response.status_code == 200
    result = run(agent, response.json()["id"], monkeypatch, [effect(agent)])
    assert result["status"] == "failed"
    assert not agent[7]


def test_continuation_waits_for_previous_worker_lock(agent, monkeypatch):
    from contextlib import contextmanager

    attempts = []
    original = runtime.execution_lock

    @contextmanager
    def held(factory, key):
        attempts.append(key)
        if len(attempts) == 1:
            yield False
        else:
            with original(factory, key) as acquired:
                yield acquired

    monkeypatch.setattr(runtime, "execution_lock", held)
    result = run(agent, start(agent), monkeypatch, [{"kind": "finish", "message": "No action"}])
    assert len(attempts) == 2
    assert result["status"] == "unverified"


def test_chat_continuity_stays_local_and_revision_bound(agent):
    from hub.db import Message

    with agent[0].state.sessions() as db:
        message = Message(conversation_id=agent[5], role="user", content="Private prior goal")
        db.add(message)
        db.commit()
        message_id = message.id
    job_id = start(agent)
    with agent[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert any(
            part["content"].endswith("Private prior goal") for part in json.loads(job.context)
        )
        runtime.gate(db, agent[3], job)
        db.get(Message, message_id).revision += 1
        db.commit()
        with pytest.raises(PermissionError, match="Gesprächskontext"):
            runtime.gate(db, agent[3], job)


def test_authority_can_be_revoked_while_remote_operation_waits(agent, monkeypatch):
    job_id = start(agent)

    async def generate(*args):
        return effect(agent)

    def waiting(cfg, config, secret, tool, args, rules, boundary):
        boundary()
        # A separate writer must be able to commit after dispatch/authentication,
        # rather than waiting for a remote command to finish.
        with agent[0].state.sessions() as db:
            policy = db.get(ActionPolicy, 1)
            policy.paused = True
            policy.revision += 1
            db.commit()
        boundary()  # The next periodic/follow-up boundary sees that revocation.
        raise AssertionError("Revoked operation continued")

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", waiting)
    asyncio.run(runtime.execute_agent(agent[0].state.sessions, agent[3], None, job_id))
    result = agent[1].get("/api/agent-runs/" + job_id).json()
    assert result["status"] == "uncertain"
    assert not agent[7]


def test_stalled_agent_queue_is_recovered_from_heartbeat_only():
    from types import SimpleNamespace

    from hub.jobs import requeue_stalled

    checked, retried = [], []

    async def stalled(**kwargs):
        checked.append(kwargs)
        return ["synthetic-stalled-agent"] if kwargs["task_name"] == "hub.agent" else []

    async def retry(job):
        retried.append(job)

    queue = SimpleNamespace(job_manager=SimpleNamespace(get_stalled_jobs=stalled, retry_job=retry))
    asyncio.run(requeue_stalled(queue))
    assert retried == ["synthetic-stalled-agent"]
    assert all(item["seconds_since_heartbeat"] == 60 for item in checked)


def test_project_chat_uses_inherited_targets_and_same_effect_verification(agent, monkeypatch):
    client, headers = agent[1:3]
    project = client.post(
        "/api/projects", json={"name": "Synthetic agent project"}, headers=headers
    )
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]
    bound = client.put(
        "/api/integration-bindings/project/" + project_id,
        json={"expected_revision": 0, "integration_ids": [agent[4]], "selection_mode": "manual"},
        headers=headers,
    )
    assert bound.status_code == 200, bound.text
    chat = client.post("/api/conversations", json={"project_id": project_id}, headers=headers)
    assert chat.status_code == 200, chat.text
    context = (*agent[:5], chat.json()["id"], *agent[6:])
    decisions = [
        effect(context),
        {
            "kind": "tool",
            "message": "Verify",
            "integration_id": agent[4],
            "tool": "http.verify",
            "arguments": {
                "path": "/api/documents/1/",
                "effect_step": 1,
                "expected": {"/body/title": "After"},
            },
        },
        {"kind": "finish", "message": "Project effect checked"},
    ]
    # Model generation records are replaced in this unit test, so the first tool
    # occupies sequence one exactly as in the other orchestration checks.
    result = run(context, start(context), monkeypatch, decisions)
    assert result["status"] == "succeeded"
    assert len(agent[7]) == 1


@pytest.mark.parametrize(
    ("status", "effect_status", "verified", "should_pause"),
    [
        ("uncertain", None, False, True),
        ("unverified", "succeeded", False, True),
        ("failed", "succeeded", False, True),
        ("cancelled", "dispatching", False, True),
        ("failed", "prepared", False, False),
        ("failed", "succeeded", True, False),
    ],
)
def test_unresolved_scheduled_effect_pauses_task_before_next_occurrence(
    agent, status, effect_status, verified, should_pause
):
    from hub.db import Task, TaskRun

    task = (
        agent[1]
        .post(
            "/api/tasks",
            headers=agent[2],
            json={
                "title": "Synthetic recurring administration",
                "goal": "Inspect then change",
                "steps": [{"tool_id": "agent.run"}],
                "autonomy": "bounded_autonomous",
                "success_criterion": "all_steps_completed",
                "timeout_seconds": 600,
            },
        )
        .json()
    )
    task = (
        agent[1]
        .patch(
            "/api/tasks/" + task["id"] + "/control",
            headers=agent[2],
            json={
                "expected_revision": task["revision"],
                "expected_control_revision": task["control_revision"],
                "paused": False,
            },
        )
        .json()
    )
    job_id = start(agent)
    with agent[0].state.sessions() as db:
        run = TaskRun(
            task_id=task["id"],
            task_revision=task["revision"],
            control_revision=task["control_revision"],
            request_key=str(uuid4()),
            request_digest="a" * 64,
            snapshot="{}",
        )
        db.add(run)
        db.flush()
        job = db.get(AgentJob, job_id)
        job.task_run_id, job.owner_id, job.scope = run.id, task["id"], "task"
        if effect_status:
            step = runtime.record(db, job, "effect", {"message": "Synthetic effect"})
            step.status = effect_status
            step.result = json.dumps({"effect_verified": verified})
            db.flush()
        runtime.complete(db, job, status, "Synthetic terminal result")
        db.commit()
        current = db.get(Task, task["id"])
        assert current.paused == should_pause
        assert current.control_revision == task["control_revision"] + int(should_pause)
        assert run.status == ("cancelled" if status == "cancelled" else "failed")
        assert ("ausdrücklich wieder aktivierst" in job.summary) == should_pause


def test_failed_remote_script_stops_before_new_effects(agent, monkeypatch):
    job_id = start(agent)
    with agent[0].state.sessions() as db:
        step = runtime.record(
            db,
            db.get(AgentJob, job_id),
            "effect",
            {
                "integration_id": agent[4],
                "tool": "shell",
                "arguments": {},
                "message": "Synthetic script",
            },
        )
        sequence = step.sequence
        db.commit()
    monkeypatch.setattr(runtime, "validate_tool", lambda *a: ({}, True))

    def failed(cfg, config, secret, tool, args, rules, boundary):
        boundary()
        return {"exit_code": 1, "effect_verified": False}

    monkeypatch.setattr(runtime, "invoke", failed)
    runtime.dispatch(agent[0].state.sessions, agent[3], job_id, sequence)
    result = agent[1].get("/api/agent-runs/" + job_id).json()
    assert result["steps"][0]["status"] == "uncertain"


def test_invalid_model_envelope_gets_feedback_without_inferring_target(agent, monkeypatch):
    bad = {"kind": "shell", "tool": "shell", "message": "Inspect", "arguments": {}}
    verify = {
        "kind": "tool",
        "tool": "http.verify",
        "integration_id": agent[4],
        "message": "Verify",
        "arguments": {
            "path": "/api/documents/1/",
            "effect_step": 2,
            "expected": {"/body/title": "After"},
        },
    }
    result = run(
        agent,
        start(agent),
        monkeypatch,
        [bad, effect(agent), verify, {"kind": "finish", "message": "Checked"}],
    )
    assert result["status"] == "succeeded"
    feedback = [s for s in result["steps"] if s["kind"] == "feedback"]
    assert len(feedback) == 1
    assert feedback[0]["document"]["rejected_decision"] == bad
    assert len(agent[7]) == 1


def test_model_format_correction_is_bounded_and_never_dispatches_invalid_data(agent, monkeypatch):
    bad = {"kind": "shell", "tool": "shell", "message": "Invalid", "arguments": {}}
    result = run(agent, start(agent), monkeypatch, [bad, bad, bad])
    assert result["status"] == "failed"
    assert len([s for s in result["steps"] if s["kind"] == "feedback"]) == 2
    assert not any(s["kind"] == "effect" for s in result["steps"])
    assert not agent[7]


def test_exhausted_format_correction_preserves_acknowledged_unverified_effect(agent, monkeypatch):
    bad = {"kind": "shell", "tool": "shell", "message": "Invalid", "arguments": {}}
    result = run(agent, start(agent), monkeypatch, [effect(agent), bad, bad, bad])
    assert result["status"] == "failed"
    effects = [s for s in result["steps"] if s["kind"] == "effect"]
    assert len(effects) == len(agent[7]) == 1
    assert effects[0]["status"] == "succeeded"
    assert not effects[0]["result"]["effect_verified"]


def test_tool_argument_validation_uses_feedback_before_creating_intent(agent, monkeypatch):
    bad = effect(agent)
    bad["arguments"]["method"] = "BOOM"
    result = run(
        agent, start(agent), monkeypatch, [bad, {"kind": "finish", "message": "No action"}]
    )
    assert result["status"] == "unverified"
    assert result["steps"][0]["kind"] == "feedback"
    assert not agent[7]


def test_invalid_json_can_be_corrected_locally_before_tools(agent, monkeypatch):
    attempts = []

    async def generate(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise runtime.AgentFormatError("not JSON")
        return {"kind": "finish", "message": "No action"}

    monkeypatch.setattr(runtime, "generate", generate)
    job_id = start(agent)
    asyncio.run(runtime.execute_agent(agent[0].state.sessions, agent[3], None, job_id))
    result = agent[1].get("/api/agent-runs/" + job_id).json()
    assert result["status"] == "unverified" and len(attempts) == 2
    assert result["steps"][0]["document"]["rejected_decision"] == "not JSON"
    assert not agent[7]
