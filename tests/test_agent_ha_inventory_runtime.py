"""API/worker proof of bounded HA inventory without speculative model planning."""

# ruff: noqa: F811

import json

import pytest
from hub import agent_runtime as runtime
from hub.agent_context import project
from hub.agent_models import AgentJob, AgentPolicy, AgentStep
from test_actions import gateway, set_pause  # noqa: F401
from test_agent_capability_runtime import execute, ha, no_planning, start  # noqa: F401
from test_agents import agent  # noqa: F401
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
        assert tool == "http" and args["path"] == "/api/"
        calls.append(args)
        return {"http_status": 200, "body": {"message": "API running."}}

    async def model(*args):
        model_calls.append(args[-1])
        return {"kind": "finish", "message": "Synthetic general administration reviewed."}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha, "Prüfe Home Assistant und ermittle die verfügbaren Dienste."))
    assert result["status"] == "observed" and len(model_calls) == 1
    assert len(calls) == 1 and not ha[-1]
