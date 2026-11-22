"""Actual API/worker boundaries for semantic targets and unmet evidence."""

# ruff: noqa: F811

import asyncio
import json
from uuid import uuid4

import pytest
from hub import agent_runtime as runtime
from hub.agent_intent import RequestIntent, Requirement
from hub.agent_models import AgentPolicy
from hub.agent_tools import Rules
from hub.gmail_client import API_BASE
from hub.integrations import Integration
from test_actions import gateway, set_pause  # noqa: F401
from test_agent_capability_runtime import ha  # noqa: F401
from test_agents import agent  # noqa: F401
from test_integration_routing import add_profile
from test_integration_writes import writes  # noqa: F401


def execute(ha, job):
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, job))
    return ha[1].get("/api/agent-runs/" + job).json()


def start(ha, goal):
    response = ha[1].post(
        f"/api/conversations/{ha[5]}/agent-runs",
        json={"request_id": str(uuid4()), "goal": goal, "research_allowed": False}, headers=ha[2],
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_broad_sensor_projection_is_narrowed_before_durable_preparation_and_dispatch(
    ha, monkeypatch,
):
    from hub.agent_context import project

    observed = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        if args["path"] == "/api/":
            return {"http_status": 200, "body": {"message": "API running."}}
        observed.append(args)
        assert args["projection"]["where_prefix"] == "sensor."
        return {"http_status": 200, "body": project([
            {"entity_id": "sensor.temperature", "state": "20"},
            {"entity_id": "light.room", "state": "on"},
        ], args["projection"])}

    async def model(*args):
        if not observed:
            return {"kind": "tool", "integration_id": ha[4], "tool": "http",
                    "arguments": {"method": "GET", "path": "/api/states", "projection": {
                        "items_path": "", "fields": [], "limit": 100,
                    }}, "message": "Read sensor inventory"}
        return {"kind": "finish", "message": "sensor.temperature: 20 (one sensor)."}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha, "Welche Sensoren habe ich in Home Assistant?"))
    assert result["status"] == "observed" and len(observed) == 1
    with ha[0].state.sessions() as db:
        from hub.agent_models import AgentStep
        from sqlalchemy import select

        steps = db.scalars(select(AgentStep).where(AgentStep.job_id == result["id"])).all()
        actual = [json.loads(s.document) for s in steps if s.kind == "read"][-1]
        assert actual["arguments"]["projection"]["where_prefix"] == "sensor."


def test_mixed_request_does_not_prepare_effects_on_its_observation_only_target(ha, monkeypatch):
    from hub.agent_models import AgentJob

    other = add_profile(ha[0], kind="home_assistant", name="Other installation", rules=Rules(
        enabled=True, autonomous=True, http_prefixes=["/api/"], http_methods=["GET", "POST"],
    ))
    response = ha[1].put(
        "/api/integration-bindings/conversation/" + ha[5],
        json={"expected_revision": 1, "selection_mode": "manual",
              "integration_ids": [ha[4], other]}, headers=ha[2],
    )
    assert response.status_code == 200, response.text
    job_id = start(ha, "Welche Sensoren habe ich in Home Assistant?")
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        binding = json.loads(job.bindings)
        binding["intent"] = RequestIntent(
            target_ids=[ha[4], other], mode="admin", topic="general",
            requirements=[Requirement(kind="system", integration_id=ha[4]),
                          Requirement(kind="effect_postcondition", integration_id=other)],
        ).model_dump()
        job.bindings = json.dumps(binding)
        db.commit()
    turns, calls = [], []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        assert args["method"] == "GET"
        calls.append(args)
        return {"http_status": 200, "body": {"message": "API running."}}

    async def model(*args):
        data = args[-1]
        turns.append(data)
        observed = next(row for row in data["interfaces"] if row["integration_id"] == ha[4])
        assert observed["read_only"] and observed["rules"]["http_methods"] == ["GET"]
        if len(turns) == 1:
            return {"kind": "tool", "tool": "http", "integration_id": ha[4],
                    "arguments": {"method": "POST", "path": "/api/services/light/turn_on",
                                  "verification": {"path": "/api/", "expected": {
                                      "/http_status": 200}}}, "message": "Never authorized here"}
        return {"kind": "stop", "message": "Cannot complete the other target's requested change"}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, job_id)
    assert len(turns) == 2 and calls
    assert not any(step["kind"] == "effect" for step in result["steps"])
    assert any(step["kind"] == "feedback" for step in result["steps"])


def test_prepared_effect_cannot_bypass_frozen_observation_target_at_dispatch(ha, monkeypatch):
    from hub.agent_models import AgentJob

    job_id = start(ha, "Welche Sensoren habe ich in Home Assistant?")
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        prepared = runtime.record(db, job, "effect", {
            "integration_id": ha[4], "tool": "http", "arguments": {
                "method": "POST", "path": "/api/services/light/turn_on",
                "verification": {"path": "/api/", "expected": {"/http_status": 200}},
            },
        })
        sequence = prepared.sequence
        db.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("No transport for a prepared effect lacking a target-bound change")

    monkeypatch.setattr(runtime, "invoke", forbidden)
    with pytest.raises(PermissionError, match="Beobachtungen"):
        runtime.dispatch(ha[0].state.sessions, ha[3], job_id, sequence)


def test_effect_target_is_rechecked_at_the_final_transport_boundary(ha, monkeypatch):
    from hub.agent_models import AgentJob

    job_id = start(ha, "Welche Sensoren habe ich in Home Assistant?")
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        binding = json.loads(job.bindings)
        binding["read_only"] = False
        binding["intent"] = RequestIntent(
            target_ids=[ha[4]], mode="admin", topic="general",
            requirements=[Requirement(kind="effect_postcondition", integration_id=ha[4])],
        ).model_dump()
        job.bindings, job.max_effects = json.dumps(binding), 2
        prepared = runtime.record(db, job, "effect", {
            "integration_id": ha[4], "tool": "http", "arguments": {
                "method": "POST", "path": "/api/services/light/turn_on",
                "verification": {"path": "/api/", "expected": {"/http_status": 200}},
            },
        })
        sequence = prepared.sequence
        db.commit()
    boundaries = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        with ha[0].state.sessions() as db:
            job = db.get(AgentJob, job_id)
            binding = json.loads(job.bindings)
            binding["intent"]["requirements"] = [{"kind": "system", "integration_id": ha[4]}]
            job.bindings = json.dumps(binding)
            db.commit()
        with pytest.raises(PermissionError):
            before_send()
        boundaries.append("blocked before transport")
        raise PermissionError("Synthetic boundary prevented transport")

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr("hub.agent_reconcile.verify", lambda *args: {"effect_verified": False})
    runtime.dispatch(ha[0].state.sessions, ha[3], job_id, sequence)
    assert boundaries == ["blocked before transport"]


@pytest.mark.parametrize("revoke_other", [False, True])
def test_semantic_selected_target_only_in_schema_and_dispatch_but_full_revocation_stays(
    ha, monkeypatch, revoke_other,
):
    other = add_profile(ha[0], kind="home_assistant", name="Other installation", rules=Rules(
        enabled=True, http_prefixes=["/api/"], http_methods=["GET"],
    ))
    selection = ha[1].put(
        "/api/integration-bindings/conversation/" + ha[5],
        json={"expected_revision": 1, "selection_mode": "manual",
              "integration_ids": [ha[4], other]}, headers=ha[2],
    )
    assert selection.status_code == 200, selection.text
    calls, plans, interpretations = [], [], []

    async def generate(*args):
        data = args[-1]
        if data.get("intent_schema"):
            interpretations.append(data)
            assert {row["id"] for row in data["targets"]} == {ha[4], other}
            if revoke_other:
                with ha[0].state.sessions() as db:
                    policy = db.get(AgentPolicy, other)
                    policy.rules = Rules(enabled=False).model_dump_json()
                    db.commit()
            return RequestIntent(
                target_ids=[ha[4]], mode="observe", topic="system", origin="semantic",
                requirements=[Requirement(kind="system", integration_id=ha[4])],
            ).model_dump()
        plans.append(data)
        assert [row["integration_id"] for row in data["interfaces"]] == [ha[4]]
        assert data["read_only"]
        assert data["interfaces"][0]["rules"]["http_methods"] == ["GET"]
        assert not {"shell", "http.verify", "http.upload", "mail.send"} & set(data["tools"])
        if len(plans) == 1:
            return {"kind": "tool", "integration_id": ha[4], "tool": "http",
                    "arguments": {"method": "GET", "path": "/api/config"},
                    "message": "Konfiguration tatsächlich lesen"}
        return {"kind": "finish", "message": "Verbindung tatsächlich geprüft."}

    def invoke(cfg, config, secret, tool, arguments, rules, before_send):
        before_send()
        calls.append((config["url"], tool, arguments))
        assert config["url"] == "https://ha.example.test"
        return {"http_status": 200, "body": {"message": "API running."}}

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", invoke)
    result = execute(ha, start(ha, "Bitte gib mir einen kompakten Überblick über die Verbindung"))
    assert len(interpretations) == 1
    if revoke_other:
        assert result["status"] == "failed" and not calls and not plans
    else:
        assert result["status"] == "observed" and len(calls) == len(plans) == 2
    assert not ha[-1]


@pytest.mark.parametrize("goal", [
    "Welche Gmail-Mails besitzen eine Antwort von mir?", "Which Gmail messages did I respond to?",
])
def test_gmail_reply_missing_capability_uses_typed_requirement_before_any_dispatch(
    agent, monkeypatch, goal,
):
    monkeypatch.setattr("hub.gmail_setup.read_ready", lambda *args: True)
    with agent[0].state.sessions() as db:
        profile = db.get(Integration, agent[4])
        profile.kind, profile.name, profile.writes_enabled = "gmail", "Synthetic Gmail", False
        profile.config = json.dumps({"kind": "gmail", "url": API_BASE,
                                     "auth": "oauth"})
        policy = db.get(AgentPolicy, agent[4])
        policy.rules = Rules(enabled=True, gmail_read=True, max_effects=0).model_dump_json()
        db.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("Missing reply evidence cannot be replaced by an unrelated tool")

    async def no_model(*args, **kwargs):
        raise AssertionError("Certain typed reply intent needs no model or speculative research")

    monkeypatch.setattr(runtime, "invoke", forbidden)
    monkeypatch.setattr(runtime, "generate", no_model)
    monkeypatch.setattr(runtime, "research", no_model)
    result = execute(agent, start(agent, goal))
    assert result["status"] == "unverified" and "Gmail" in result["summary"]
    assert not result["steps"]


@pytest.mark.parametrize("attempt_write", [False, True, "malformed"])
def test_exhausted_tool_budget_has_one_finish_only_turn_from_real_sensor_evidence(
    ha, monkeypatch, attempt_write,
):
    from hub.agent_context import project
    from hub.agent_models import AgentJob

    goal = "Welche Sensoren habe ich in Home Assistant?"
    job_id = start(ha, goal)
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        job.max_steps = 2
        db.commit()
    calls, turns = [], []
    projection = {"items_path": "", "where_pointer": "/entity_id", "where_prefix": "sensor.",
                  "fields": ["/entity_id", "/state"], "limit": 100}

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        calls.append(args["path"])
        assert args["method"] == "GET"
        body = ({"message": "API running."} if args["path"] == "/api/" else project([
            {"entity_id": "sensor.synthetic_temperature", "state": "20"},
        ], projection))
        return {"http_status": 200, "body": body}

    async def model(*args):
        data = args[-1]
        turns.append(data)
        assert not data.get("intent_schema") and len(turns) <= 2
        assert data["request_contract"]["target_ids"] == [ha[4]]
        assert data["request_contract"]["requirements"][0]["domain"] == "sensor"
        if len(turns) == 1:
            return {"kind": "tool", "integration_id": ha[4], "tool": "http",
                    "arguments": {"method": "GET", "path": "/api/states", "projection": projection},
                    "message": "Sensoren lesen"}
        assert data["summarize_only"] and data["tools"] == {}
        assert all(branch["properties"]["kind"].get("const") != "tool"
                   for branch in data["decision_schema"]["anyOf"])
        if attempt_write == "malformed":
            return {"kind": "invalid"}
        if attempt_write:
            return {"kind": "tool", "integration_id": ha[4], "tool": "http",
                    "arguments": {"method": "POST", "path": "/api/services/light/turn_on"},
                    "message": "Must never dispatch"}
        return {"kind": "finish", "message": "sensor.synthetic_temperature meldet 20."}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, job_id)
    assert calls == ["/api/", "/api/states"] and len(turns) == 2
    assert result["status"] == ("unverified" if attempt_write else "observed")
    if not attempt_write:
        assert "synthetic_temperature" in result["summary"]
    assert not any(step["kind"] == "effect" for step in result["steps"])


@pytest.mark.parametrize(("mode", "confidence"), [
    ("unknown", "certain"), ("explain", "certain"), ("observe", "uncertain"),
])
def test_non_actionable_frozen_intent_cannot_inherit_selected_admin_tools(
    ha, monkeypatch, mode, confidence,
):
    from hub.agent_models import AgentJob

    job_id = start(ha, "Welche Sensoren habe ich in Home Assistant?")
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        frozen = json.loads(job.bindings)
        frozen["intent"] = RequestIntent(
            target_ids=[] if mode == "explain" else [ha[4]], mode=mode, topic="general",
            confidence=confidence, origin="semantic",
        ).model_dump()
        job.bindings = json.dumps(frozen)
        db.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("Unclear interpretation must not inherit admin tools or dispatch")

    async def no_model(*args, **kwargs):
        raise AssertionError("No further planning before the ambiguous request is resolved")

    monkeypatch.setattr(runtime, "invoke", forbidden)
    monkeypatch.setattr(runtime, "generate", no_model)
    result = execute(ha, job_id)
    assert result["status"] == "unverified" and not result["steps"]
    assert "kein Werkzeug" in result["summary"]


def test_explicit_state_followup_without_displayed_cohort_never_scans_all_devices(ha, monkeypatch):
    job_id = start(ha, "Welche davon sind an?")

    def forbidden(*args, **kwargs):
        raise AssertionError("No valid source cohort, therefore no fresh arbitrary inventory scan")

    async def no_model(*args, **kwargs):
        raise AssertionError("Missing evidence is not replaced by model assumptions")

    monkeypatch.setattr(runtime, "invoke", forbidden)
    monkeypatch.setattr(runtime, "generate", no_model)
    result = execute(ha, job_id)
    assert result["status"] == "unverified" and not result["steps"]
    assert "Abrufbeleg" in result["summary"]
