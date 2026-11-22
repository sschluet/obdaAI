"""A bounded alternative read can recover a guessed endpoint without replay or new authority."""

# ruff: noqa: F811

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from hub import agent_runtime as runtime
from hub.agent_context import project
from hub.agent_intent import RequestIntent, Requirement
from hub.agent_models import AgentJob
from hub.agent_tools import validate_tool
from test_actions import gateway, set_pause  # noqa: F401
from test_agent_capability_runtime import ha  # noqa: F401
from test_agents import agent  # noqa: F401
from test_integration_writes import writes  # noqa: F401

# Exercise the general planner; the short inventory-only question has a native read path.
GOAL = ("Welche Lampen sind in meinem Home Assistant vorhanden? "
        "Prüfe die verfügbaren Schnittstellen.")
STATES = [
    {"entity_id": "light.synthetic_living", "state": "on",
     "attributes": {"friendly_name": "Synthetic living room"}},
    {"entity_id": "sensor.synthetic_temperature", "state": "20", "attributes": {}},
    {"entity_id": "light.synthetic_kitchen", "state": "off",
     "attributes": {"friendly_name": "Synthetic kitchen"}},
]


def start(ha):
    response = ha[1].post(
        f"/api/conversations/{ha[5]}/agent-runs",
        json={"request_id": str(uuid4()), "goal": GOAL, "research_allowed": False},
        headers=ha[2],
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def execute(ha, identifier):
    planner = runtime.generate
    intent_turns = []

    async def semantic_then_planner(*args):
        data = args[-1]
        if data.get("intent_schema"):
            intent_turns.append(data)
            assert len(intent_turns) == 1 and data["goal"] == GOAL
            return RequestIntent(
                target_ids=[ha[4]], mode="observe", topic="inventory", origin="semantic",
                requirements=[Requirement(kind="entity_states", domain="light",
                                          integration_id=ha[4])],
            ).model_dump()
        return await planner(*args)

    runtime.generate = semantic_then_planner
    try:
        asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, identifier))
    finally:
        runtime.generate = planner
    assert len(intent_turns) == 1
    response = ha[1].get("/api/agent-runs/" + identifier)
    assert response.status_code == 200, response.text
    return response.json()


def decision(ha, path, **arguments):
    return {"kind": "tool", "integration_id": ha[4], "tool": "http",
            "arguments": {"method": "GET", "path": path, **arguments},
            "message": "Freigegebenen Status lesen"}


def fake_target(monkeypatch, *, guessed_status=404):
    calls = []

    def invoke(cfg, config, secret, tool, arguments, rules, before_send):
        before_send()
        assert secret == "synthetic-write-token"
        calls.append((tool, dict(arguments)))
        assert tool == "http" and arguments["method"] == "GET", "No effect may be dispatched"
        path = arguments["path"]
        if path == "/api/":
            return {"http_status": 200, "body": {"message": "API running."}}
        if path in {"/api/light", "/api/lights"}:
            if guessed_status == "timeout":
                raise httpx.ReadTimeout("SYNTHETIC-PRIVATE-ERROR https://private.example.invalid")
            return {"http_status": guessed_status, "body": {"text": "Not Found"}}
        assert path == "/api/states"
        assert arguments["projection"]["where_pointer"] == "/entity_id"
        assert arguments["projection"]["where_prefix"] == "light."
        return {"http_status": 200, "body": project(STATES, arguments["projection"])}

    monkeypatch.setattr(runtime, "invoke", invoke)
    return calls


def light_recipe(data):
    interface = data["interfaces"][0]
    recipes = interface["capabilities"]["operations"]["http_reads"]
    recipe = next(
        item for item in recipes
        if item["tool"] == "http" and item["arguments"]["path"] == "/api/states"
        and item["arguments"].get("projection", {}).get("where_prefix") == "light."
    )
    assert recipe["arguments"]["method"] == "GET"
    assert recipe["arguments"]["projection"]["where_pointer"] == "/entity_id"
    assert recipe["purpose"]
    return {"kind": "tool", "integration_id": interface["integration_id"],
            "tool": "http", "arguments": recipe["arguments"], "message": "Lampen lesen"}


def assert_missing_path_evidence(data, identifier):
    recovery = data["read_recovery"]
    assert recovery["integration_id"] == identifier and recovery["failed_path"] == "/api/light"
    assert recovery["needs_alternative"] is True and recovery["instruction"]
    failed = next(step for step in data["history"] if step["status"] == "failed")
    assert failed["kind"] == "read" and failed["result"]["failure_category"] == "not_found"
    assert failed["document"]["arguments"]["path"] == "/api/light"


def test_missing_ha_domain_path_recovers_with_real_state_projection_and_preserved_failure(
    ha, monkeypatch
):
    calls = fake_target(monkeypatch)
    turns = []

    async def model(factory, cfg, providers, job_id, instruction, data):
        turns.append(data)
        if len(turns) == 1:
            return decision(ha, "/api/light")
        if len(turns) == 2:
            assert_missing_path_evidence(data, ha[4])
            return light_recipe(data)
        assert data["read_recovery"]["needs_alternative"] is False
        body = data["history"][-1]["result"]["body"]
        assert body["matched"] == 2 and body["returned"] == 2
        assert all(item["/entity_id"].startswith("light.") for item in body["items"])
        return {"kind": "finish", "message": "Zwei Lampen: Wohnzimmer an, Küche aus."}

    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha))
    assert result["status"] == "observed" and len(turns) == 3
    assert [args["path"] for tool, args in calls] == ["/api/", "/api/light", "/api/states"]
    failed = [step for step in result["steps"] if step["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["result"]["http_status"] == 404
    assert not any(step["kind"] == "effect" for step in result["steps"])
    assert not ha[-1]


def test_repeated_same_missing_get_is_never_dispatched_and_feedback_is_bounded(ha, monkeypatch):
    calls = fake_target(monkeypatch)
    turns = []

    async def model(*args):
        turns.append(args[-1])
        if len(turns) > 1:
            assert_missing_path_evidence(args[-1], ha[4])
        assert len(turns) <= 4, "Endpoint recovery must not create an endless correction loop"
        return decision(ha, "/api/light")

    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha))
    assert result["status"] == "failed"
    assert [args["path"] for tool, args in calls] == ["/api/", "/api/light"]
    assert len([s for s in result["steps"] if s["kind"] == "feedback"]) <= 2
    assert not any(s["kind"] == "effect" for s in result["steps"])


def test_second_distinct_missing_read_is_terminal_instead_of_starting_another_recovery(
    ha, monkeypatch
):
    calls = fake_target(monkeypatch)
    turns = []

    async def model(*args):
        turns.append(args[-1])
        assert len(turns) <= 2
        return decision(ha, "/api/light" if len(turns) == 1 else "/api/lights")

    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha))
    assert result["status"] == "failed" and len(turns) == 2
    assert [args["path"] for tool, args in calls] == ["/api/", "/api/light", "/api/lights"]
    assert len([s for s in result["steps"] if s["kind"] == "read" and s["status"] == "failed"]) == 2


@pytest.mark.parametrize("tool", ["http", "ha.websocket"])
def test_recovery_cannot_dispatch_an_effect_before_a_successful_alternative_read(
    ha, monkeypatch, tool
):
    calls = fake_target(monkeypatch)
    turns = []

    async def model(*args):
        turns.append(args[-1])
        assert len(turns) <= 4
        if len(turns) == 1:
            return decision(ha, "/api/light")
        assert_missing_path_evidence(args[-1], ha[4])
        arguments = ({"method": "POST", "path": "/api/services/light/turn_on",
                      "body": {"entity_id": "light.synthetic_living"}}
                     if tool == "http" else {
                         "type": "config/entity_registry/list", "parameters": {},
                     })
        return {"kind": "tool", "integration_id": ha[4], "tool": tool,
                "arguments": arguments, "message": "Do not dispatch while read recovery is pending"}

    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha))
    assert result["status"] == "failed"
    assert [args["path"] for name, args in calls] == ["/api/", "/api/light"]
    assert not any(s["kind"] == "effect" for s in result["steps"])
    assert not ha[-1]


@pytest.mark.parametrize("outcome", [401, 403, "timeout"])
def test_authentication_and_transport_failures_remain_terminal(ha, monkeypatch, outcome):
    calls = fake_target(monkeypatch, guessed_status=outcome)
    turns = []

    async def model(*args):
        turns.append(args[-1])
        assert len(turns) == 1, "Only a missing read endpoint can request an alternative"
        return decision(ha, "/api/light")

    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha))
    assert result["status"] == "failed" and len(calls) == 2 and len(turns) == 1
    assert "SYNTHETIC-PRIVATE-ERROR" not in json.dumps(result)
    assert "private.example.invalid" not in json.dumps(result)


def test_missing_read_after_unverified_effect_stays_uncertain_and_is_not_replanned(
    ha, monkeypatch
):
    calls = fake_target(monkeypatch)

    async def forbidden(*args):
        raise AssertionError("An unverified effect cannot enter read-endpoint recovery")

    monkeypatch.setattr(runtime, "generate", forbidden)
    job_id = start(ha)
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        profile, rules, _ = runtime.gate(db, ha[3], job)[ha[4]]
        args, _ = validate_tool(profile.kind, rules, "http", {
            "method": "POST", "path": "/api/services/light/turn_on",
            "body": {"entity_id": "light.synthetic_living"},
        })
        effect = runtime.record(db, job, "effect", {
            "tool": "http", "integration_id": ha[4], "arguments": args,
        })
        effect.status, effect.result = "succeeded", json.dumps({"effect_verified": False})
        args, _ = validate_tool(
            profile.kind, rules, "http", {"method": "GET", "path": "/api/light"}
        )
        runtime.record(db, job, "read", {
            "tool": "http", "integration_id": ha[4], "arguments": args,
        })
        db.commit()
    result = execute(ha, job_id)
    assert result["status"] == "uncertain" and len(calls) == 1
    assert result["steps"][-1]["status"] == "failed"
    assert not result["steps"][0]["result"]["effect_verified"]


def test_read_recovery_cannot_exceed_the_remaining_operation_budget(ha, monkeypatch):
    calls = fake_target(monkeypatch)
    turns = []

    async def model(*args):
        turns.append(args[-1])
        if len(turns) == 1:
            return decision(ha, "/api/light")
        return light_recipe(args[-1])

    monkeypatch.setattr(runtime, "generate", model)
    job_id = start(ha)
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        job.max_steps = 2  # Tighten this request below its profile's standing maximum.
        db.commit()
    result = execute(ha, job_id)
    assert result["status"] == "unverified"
    assert [args["path"] for tool, args in calls] == ["/api/", "/api/light"]
    assert len([s for s in result["steps"] if s["kind"] in {"read", "effect"}]) <= 2


@pytest.mark.parametrize("kind", ["ask", "finish"])
def test_pending_alternative_read_cannot_turn_into_confirmation_or_unsupported_success(
    ha, monkeypatch, kind
):
    calls = fake_target(monkeypatch)
    turns = []

    async def model(*args):
        turns.append(args[-1])
        assert len(turns) <= 4
        if len(turns) == 1:
            return decision(ha, "/api/light")
        return {"kind": kind, "message": "No unsupported answer or unnecessary confirmation"}

    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha))
    assert result["status"] == "failed"
    assert [args["path"] for tool, args in calls] == ["/api/", "/api/light"]
