"""API/worker proof of bounded HA inventory without speculative model planning."""

# ruff: noqa: F811

import json
from uuid import uuid4

import pytest
from hub import agent_runtime as runtime
from hub.agent_context import project
from hub.agent_models import AgentJob, AgentPolicy, AgentStep
from test_actions import gateway, set_pause  # noqa: F401
from test_agent_capability_runtime import execute, ha, no_planning, start  # noqa: F401
from test_agents import agent  # noqa: F401
from test_integration_routing import add_profile
from test_integration_writes import writes  # noqa: F401

GOAL = "Welche Lampen sind in meinem Home Assistant vorhanden?"
STATES = [
    {"entity_id": "light.synthetic_living", "state": "on",
     "attributes": {"friendly_name": "Synthetic living room"}},
    {"entity_id": "sensor.synthetic_temperature", "state": "20", "attributes": {}},
    {"entity_id": "light.synthetic_kitchen", "state": "off",
     "attributes": {"friendly_name": "Synthetic kitchen"}},
]


def target(ha, monkeypatch, *, states=None, result=None, after_send=None):
    calls = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        assert secret == "synthetic-write-token" and config["kind"] == "home_assistant"
        assert tool == "http" and args["method"] == "GET" and args["path"] == "/api/states"
        assert args["query"] == {} and args["body"] is None
        projection = args["projection"]
        assert projection["where_pointer"] == "/entity_id"
        assert projection["where_prefix"] == "light." and projection["limit"] == 100
        assert projection["fields"] == ["/entity_id", "/state", "/attributes/friendly_name"]
        before_send()
        calls.append(dict(args))
        if after_send:
            after_send()
        return result if result is not None else {
            "http_status": 200, "body": project(STATES if states is None else states, projection),
            "effect_verified": False,
        }

    monkeypatch.setattr(runtime, "invoke", invoke)
    return calls


def assert_no_bound_read_refs(ha):
    next_job = start(ha, GOAL)
    with ha[0].state.sessions() as db:
        context = json.loads(db.get(AgentJob, next_job).context)
        assert not any(part["source_id"].startswith("agent-read:") for part in context)


@pytest.mark.parametrize("goal", [GOAL, "Bitte liste unsere Leuchten.", "Please list our lights."])
def test_inventory_is_one_projected_read_without_model_research_or_confirmation(
    ha, monkeypatch, goal
):
    no_planning(monkeypatch)
    calls = target(ha, monkeypatch)
    identifier = start(ha, goal)
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, identifier)
        assert json.loads(job.bindings)["read_only"] is True and job.max_effects == 0
    result = execute(ha, identifier)
    assert result["status"] == "observed" and len(calls) == 1
    assert [(s["kind"], s["status"]) for s in result["steps"]] == [("read", "succeeded")]
    assert result["steps"][0]["document"]["inventory_plan"]
    assert not result["steps"][0]["approved"] and not ha[-1]
    for text in ["Synthetic living room", "Synthetic kitchen", "light.synthetic_living",
                 "light.synthetic_kitchen", "an", "aus", "Licht-Entitäten"]:
        assert text in result["summary"]
    assert "sensor.synthetic_temperature" not in result["summary"]
    assert "physisch" in result["summary"]
    execute(ha, identifier)
    assert len(calls) == 1  # Finished durable reads are never dispatched again.


def test_inventory_explicitly_limits_large_results_without_claiming_full_list(ha, monkeypatch):
    no_planning(monkeypatch)
    states = [{"entity_id": f"light.synthetic_{i}", "state": "on",
               "attributes": {"friendly_name": f"Synthetic {i}"}} for i in range(101)]
    calls = target(ha, monkeypatch, states=states)
    result = execute(ha, start(ha, GOAL))
    assert result["status"] == "observed" and len(calls) == 1
    body = result["steps"][0]["result"]["body"]
    assert body["matched"] == 101 and body["returned"] == 100 and len(body["items"]) == 100
    assert "100" in result["summary"] and "101" in result["summary"]
    assert "light.synthetic_100" not in result["summary"]


def test_same_chat_on_followup_refreshes_only_the_previously_observed_cohort(ha, monkeypatch):
    no_planning(monkeypatch)
    calls = target(ha, monkeypatch)
    initial = execute(ha, start(ha, GOAL))
    assert initial["status"] == "observed" and len(calls) == 1
    fresh = [
        {"entity_id": "light.synthetic_living", "state": "off",
         "attributes": {"friendly_name": "Synthetic living room"}},
        {"entity_id": "light.synthetic_kitchen", "state": "on",
         "attributes": {"friendly_name": "Synthetic kitchen"}},
        {"entity_id": "light.new_after_inventory", "state": "on",
         "attributes": {"friendly_name": "New unrelated light"}},
    ]
    refreshed = target(ha, monkeypatch, states=fresh)
    identifier = start(ha, "Welche davon sind an?")
    with ha[0].state.sessions() as db:
        context = json.loads(db.get(AgentJob, identifier).context)
        assert any(part["source_id"].startswith("agent-read:") for part in context)
    result = execute(ha, identifier)
    assert result["status"] == "observed" and len(refreshed) == 1
    assert "light.synthetic_kitchen" in result["summary"]
    assert "light.synthetic_living" not in result["summary"]
    assert "light.new_after_inventory" not in result["summary"]
    assert "New unrelated light" not in result["summary"]
    assert result["steps"][0]["document"]["inventory_plan"]["source_references"]
    assert not ha[-1]


@pytest.mark.parametrize("use_route", [False, True])
def test_large_followup_binds_prior_ha_with_multiple_selected_adapter_kinds(
    ha, monkeypatch, use_route,
):
    import asyncio

    from hub.agent_tools import Rules

    no_planning(monkeypatch)
    other_ids = [add_profile(ha[0], kind=kind, name="Synthetic " + kind, rules=rules)
                 for kind, rules in [
                     ("paperless", Rules(enabled=True, http_methods=["GET"],
                                         http_prefixes=["/api/"])),
                     ("ssh", Rules(enabled=True, shell=True)),
                     ("mcp", Rules(enabled=True, mcp=True)),
                 ]]
    selected = ha[1].put(
        "/api/integration-bindings/conversation/" + ha[5], headers=ha[2],
        json={"expected_revision": 1, "selection_mode": "manual",
              "integration_ids": [ha[4], *other_ids]},
    )
    assert selected.status_code == 200, selected.text
    states = [{"entity_id": f"light.synthetic_{i}", "state": "on" if i % 2 else "off",
               "attributes": {"friendly_name": f"Synthetic lamp {i}"}} for i in range(75)]
    calls = target(ha, monkeypatch, states=states)
    first = start(ha, GOAL)
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, first))
    assert ha[1].get("/api/agent-runs/" + first).json()["status"] == "observed"
    if use_route:
        routed = ha[1].post(
            f"/api/conversations/{ha[5]}/integration-route", headers=ha[2],
            json={"goal": "Welche davon sind an?"},
        )
        assert routed.status_code == 200, routed.text
        assert routed.json() == {"route": "agent", "integration_ids": [ha[4]]}
    states.append({"entity_id": "light.new_unrelated", "state": "on", "attributes": {}})
    created = ha[1].post(
        f"/api/conversations/{ha[5]}/agent-runs", headers=ha[2],
        json={"request_id": str(uuid4()), "goal": "Welche davon sind an?"},
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["id"]
    with ha[0].state.sessions() as db:
        intent = json.loads(db.get(AgentJob, job_id).bindings)["intent"]
        assert intent["target_ids"] == [ha[4]] and intent["answer_kind"] == "light_on_cohort"
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, job_id))
    result = ha[1].get("/api/agent-runs/" + job_id).json()
    assert result["status"] == "observed" and len(calls) == 2
    assert len(result["steps"]) == 1 and result["steps"][0]["document"]["inventory_plan"]
    assert "new_unrelated" not in result["summary"] and not ha[-1]
    assert "light.synthetic_1" in result["summary"]


@pytest.mark.parametrize("invalidate", ["ordinary_topic", "revoked_receipt"])
def test_multi_profile_followup_cannot_reactivate_an_ineligible_previous_light_cohort(
    ha, monkeypatch, invalidate,
):
    import asyncio
    import time

    from hub.agent_intent import RequestIntent
    from hub.agent_tools import Rules
    from hub.db import Message

    other = add_profile(ha[0], kind="paperless", name="Synthetic archive", rules=Rules(
        enabled=True, http_methods=["GET"], http_prefixes=["/api/"],
    ))
    selected = ha[1].put(
        "/api/integration-bindings/conversation/" + ha[5], headers=ha[2],
        json={"expected_revision": 1, "selection_mode": "manual",
              "integration_ids": [ha[4], other]},
    )
    assert selected.status_code == 200
    calls = target(ha, monkeypatch)
    first = start(ha, GOAL)
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, first))
    assert ha[1].get("/api/agent-runs/" + first).json()["status"] == "observed"
    with ha[0].state.sessions() as db:
        if invalidate == "ordinary_topic":
            db.add(Message(conversation_id=ha[5], role="assistant", content="Other topic",
                           created=time.time() + 1))
        else:
            db.get(AgentPolicy, ha[4]).revision += 1
        db.commit()

    unknown = RequestIntent(target_ids=[], mode="unknown", topic="general",
                            confidence="uncertain").model_dump()

    async def semantic(*args, **kwargs):
        return RequestIntent.model_validate(unknown)

    async def model(*args):
        assert args[-1].get("intent_schema")
        assert args[-1]["prior_displayed_target_ids"] == []
        return unknown

    monkeypatch.setattr("hub.request_interpretation.interpret", semantic)
    monkeypatch.setattr(runtime, "generate", model)
    routed = ha[1].post(
        f"/api/conversations/{ha[5]}/integration-route", headers=ha[2],
        json={"goal": "Welche davon sind an?"},
    )
    assert routed.status_code == 200 and routed.json() == {"route": "chat", "integration_ids": []}
    job_id = start(ha, "Welche davon sind an?")
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, job_id))
    result = ha[1].get("/api/agent-runs/" + job_id).json()
    assert result["status"] == "unverified" and len(calls) == 1
    assert not any(step["kind"] in {"read", "effect"} for step in result["steps"])


def test_large_generic_followup_reaches_planner_with_bounded_prior_evidence(ha, monkeypatch):
    import asyncio

    from hub.agent_intent import RequestIntent, Requirement

    states = [{"entity_id": f"light.synthetic_{i}", "state": "on",
               "attributes": {"friendly_name": f"Synthetic lamp {i} Ä字"}} for i in range(75)]
    target(ha, monkeypatch, states=states)
    initial_id = start(ha, GOAL)
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, initial_id))
    assert ha[1].get("/api/agent-runs/" + initial_id).json()["status"] == "observed"
    job_id = start(ha, "Welche davon sind an?")
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        binding = json.loads(job.bindings)
        # Exact safe shape of the live semantic result; exercise the generic path.
        binding["intent"] = RequestIntent(
            target_ids=[ha[4]], mode="observe", topic="general", answer_kind="general",
            followup=False, origin="semantic", requirements=[Requirement(
                kind="entity_states", domain="light", integration_id=ha[4],
            )],
        ).model_dump()
        job.bindings = json.dumps(binding)
        db.commit()
        from hub.agent_read_references import model_context

        preview = model_context(db, job, runtime.gate(db, ha[3], job), max_bytes=1800)
        assert len(runtime.encode(preview).encode()) <= 1800
    planned = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        assert args["path"] == "/api/" and args["method"] == "GET"
        return {"http_status": 200, "body": {"message": "API running."}}

    async def model(*args):
        data = args[-1]
        planned.append(data)
        observations = data["prior_read_results"]
        assert len(runtime.encode(observations).encode()) <= 1800
        assert observations[0]["result_sha256"]
        return {"kind": "stop", "message": "Synthetic bounded planner reached; no extra state read"}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, job_id))
    result = ha[1].get("/api/agent-runs/" + job_id).json()
    assert result["status"] == "unverified" and len(planned) == 1


def test_policy_revoked_after_read_prevents_a_fresh_observed_answer_or_references(ha, monkeypatch):
    no_planning(monkeypatch)

    def revoke():
        with ha[0].state.sessions() as db:
            db.get(AgentPolicy, ha[4]).revision += 1
            db.commit()

    calls = target(ha, monkeypatch, after_send=revoke)
    identifier = start(ha, GOAL)
    result = execute(ha, identifier)
    assert len(calls) == 1 and result["status"] == "failed"
    assert "Synthetic living room" not in result["summary"]
    assert "light.synthetic_living" not in result["summary"]
    assert_no_bound_read_refs(ha)


@pytest.mark.parametrize("bad_result", [
    {"http_status": 401, "body": {"message": "SYNTHETIC-PRIVATE-AUTH"}},
    {"http_status": 200, "projection_error": "SYNTHETIC-PRIVATE-PROJECTION", "body": {}},
    {"http_status": 200, "body": {"items": "malformed", "matched": 2, "returned": 2}},
    {"http_status": 200, "body": {"items": [], "matched": 2, "returned": 2}},
])
def test_bad_inventory_result_is_failed_and_cannot_supply_future_read_refs(
    ha, monkeypatch, bad_result
):
    no_planning(monkeypatch)
    calls = target(ha, monkeypatch, result=bad_result)
    result = execute(ha, start(ha, GOAL))
    assert len(calls) == 1 and result["status"] == "failed"
    assert result["steps"][0]["status"] == "failed"
    assert "SYNTHETIC-PRIVATE" not in result["summary"]
    assert_no_bound_read_refs(ha)


def test_cancelling_a_prepared_inventory_never_dispatches_or_replays_it(ha, monkeypatch):
    no_planning(monkeypatch)
    calls = target(ha, monkeypatch)
    dispatch = runtime.dispatch

    def cancel_prepared(factory, cfg, job_id, sequence):
        with factory() as db:
            step = db.get(AgentStep, (job_id, sequence))
            assert step.kind == "read" and step.status == "prepared"
            assert json.loads(step.document)["inventory_plan"]
        response = ha[1].post(f"/api/agent-runs/{job_id}/cancel", headers=ha[2])
        assert response.status_code == 200
        dispatch(factory, cfg, job_id, sequence)

    monkeypatch.setattr(runtime, "dispatch", cancel_prepared)
    identifier = start(ha, GOAL)
    result = execute(ha, identifier)
    assert result["status"] == "cancelled" and not calls
    execute(ha, identifier)
    assert not calls
    assert_no_bound_read_refs(ha)


def test_general_administration_still_uses_the_ordinary_model_planner(ha, monkeypatch):
    calls, model_calls = [], []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        assert tool == "http" and args["path"] in {"/api/", "/api/services"}
        calls.append(args)
        return {"http_status": 200, "body": {"message": "API running."} if args["path"] == "/api/"
                else [{"domain": "light", "services": {"turn_on": {}}}]}

    async def model(*args):
        model_calls.append(args[-1])
        if len(model_calls) == 1:
            return {"kind": "tool", "message": "Dienste tatsächlich lesen", "integration_id": ha[4],
                    "tool": "http", "arguments": {"method": "GET", "path": "/api/services"}}
        return {"kind": "finish", "message": "Synthetic general administration reviewed."}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha, "Prüfe Home Assistant und ermittle die verfügbaren Dienste."))
    assert result["status"] == "observed" and len(model_calls) == 2
    assert len(calls) == 2 and not ha[-1]
