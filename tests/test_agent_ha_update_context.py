"""Real API/worker/fit with synthetic model text and target transport only."""
import asyncio
import json

from hub import agent_reconcile
from hub import agent_runtime as runtime
from hub.agent_intent import RequestIntent, Requirement
from hub.agent_models import AgentJob
from hub.agent_tools import Rules
from test_actions import gateway, set_pause  # noqa: F401
from test_agent_capability_runtime import ha, start  # noqa: F401
from test_agents import agent  # noqa: F401
from test_chat import FakeProviders
from test_integration_writes import writes  # noqa: F401

GOAL = "Bitte prüfe Home Assistant und spiele alle ausstehenden Update ein"


class SyntheticPlanner(FakeProviders):
    def __init__(self, identifier, decisions):
        super().__init__()
        self.identifier, self.decisions = identifier, iter(decisions)
        self.inputs = []
        self.semantic_calls = 0

    async def stream(self, parts, roles, *, external, grants):
        assert not external
        data = json.loads(parts[1].content)
        self.inputs.append(data)
        if data.get("intent_schema"):
            self.semantic_calls += 1
            answer = RequestIntent(target_ids=[self.identifier], mode="admin", topic="system",
                requirements=[Requirement(kind="system", integration_id=self.identifier),
                              Requirement(kind="effect_postcondition",
                                          integration_id=self.identifier)]
            ).model_dump(mode="json")
        else:
            assert data["request_contract"]["mode"] == "admin"
            assert {"http", "ha.websocket"}.issubset(data["tools"])
            has_effect = any(row["kind"] == "effect" and row["status"] == "succeeded"
                             for row in data["history"]) or bool(data.get("effect_ledger"))
            assert ("http.verify" in data["tools"]) == has_effect
            assert "http.upload" not in data["tools"]  # No bound source file to transfer.
            assert "$defs" in data["tools"]["http"]  # Real complete argument schema, not a stub.
            answer = next(self.decisions)
        yield json.dumps(answer)


def decision(identifier, method, path, *, body=None, expected=None):
    arguments = {"method": method, "path": path}
    if body is not None:
        arguments["body"] = body
    if expected is not None:
        arguments["verification"] = {"path": expected[0], "expected": expected[1],
                                     "timeout_seconds": 1, "interval_seconds": 1}
    return {"kind": "tool", "integration_id": identifier, "tool": "http",
            "arguments": arguments, "message": "Synthetic authorized operation"}


def scenario(
    ha, monkeypatch, uncertain, confirmations=0, execution_question=False,  # noqa: F811
    essential_question=False, goal=GOAL,
):
    app, client, headers, cfg, identifier, *_ = ha
    current = client.get(f"/api/integrations/{identifier}/agent-policy").json()
    rules = Rules.model_validate(current["rules"])
    rules.max_effects, rules.max_steps = 3, 12
    rules.file_upload = True  # A permission alone does not supply an upload source.
    response = client.put(f"/api/integrations/{identifier}/agent-policy", headers=headers, json={
        "expected_revision": current["revision"], "expected_profile_revision": 1,
        "rules": rules.model_dump(),
    })
    assert response.status_code == 200, response.text
    decisions = [
        decision(identifier, "GET", "/api/services"),
        decision(identifier, "GET", "/api/states"),
        decision(identifier, "POST", "/api/services/backup/create",
                 body={"name": "synthetic-before-update"},
                 expected=("/api/states/sensor.backup", {"/body/state": "ready"})),
        *[decision(identifier, "POST", "/api/services/update/install",
                   body={"entity_id": "update.synthetic_" + str(i)},
                   expected=("/api/states/update.synthetic_" + str(i), {"/body/state": "off"}))
          for i in (1, 2)],
        {"kind": "finish", "message": "Synthetic backup and both updates verified."},
    ]
    question = (
        "Bitte bestätigen Sie, ob ein Update der Home Assistant Instanz durchgeführt werden soll."
        if execution_question else
        'Bitte bestätige den Aufruf von http.verify mit path="/backup/info".'
    )
    if essential_question:
        question = "Welcher Auslöser und welche Aktion soll die Automation verwenden?"
    decisions = [{"kind": "ask", "message": question}
                 for _ in range(confirmations)] + decisions
    model = SyntheticPlanner(identifier, decisions)
    calls = []
    installed = set()
    backup = False
    services = [{"domain": "synthetic_" + str(i), "services": {
        "inspect": {"description": "Synthetic public service description " * 12, "fields": {}}}}
        for i in range(18)]
    services += [{"domain": "backup", "services": {"create": {"fields": {"name": {}}}}},
                 {"domain": "update", "services": {"install": {"fields": {"entity_id": {}}}}}]
    states = [{"entity_id": "update.synthetic_" + str(i), "state": "on", "attributes": {
        "installed_version": "1", "latest_version": "2", "friendly_name": "Synthetic update",
        "release_summary": "Synthetic release notes " * 140}} for i in (1, 2)]
    assert len(json.dumps(services)) > 8000 and len(json.dumps(states)) > 6000

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        nonlocal backup
        before_send()
        assert secret == "synthetic-write-token"
        calls.append((tool, args["method"] if "method" in args else "GET", args["path"],
                      args.get("body")))
        if tool == "http.verify":
            path = args["path"]
            passed = (backup if path.endswith("sensor.backup")
                      else path.rsplit("/", 1)[-1] in installed)
            return {"http_status": 200, "verification_passed": passed,
                    "body": {"state": "ready" if path.endswith("sensor.backup") else "off"}}
        if args["method"] == "POST":
            assert args["verification"]  # Predicate was persisted before the effect dispatch.
            if args["path"].endswith("backup/create"):
                backup = True
            else:
                assert backup
                if uncertain:
                    raise TimeoutError("Synthetic lost update response")
                installed.add(args["body"]["entity_id"])
            return {"http_status": 200, "body": {}, "effect_verified": False}
        body = (services if args["path"] == "/api/services"
                else states if args["path"] == "/api/states"
                else {"message": "API running."})
        return {"http_status": 200, "body": body, "effect_verified": False}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(agent_reconcile, "invoke", invoke)
    job_id = start(ha, goal, research_allowed=False)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, model, job_id))
    result = client.get("/api/agent-runs/" + job_id).json()
    before_restart = list(calls)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, model, job_id))
    assert calls == before_restart
    assert model.semantic_calls == 1
    if confirmations < 3:
        errors = [s for s in result["steps"] if s["kind"] == "error"]
        assert not errors, json.dumps(result, indent=2)
    with app.state.sessions() as db:
        frozen = json.loads(db.get(AgentJob, job_id).bindings)
        assert frozen["intent"]["mode"] == "admin"
    return result, calls, model


def test_large_ha_admin_discovery_backup_and_multiple_updates_fit_and_verify(ha, monkeypatch):  # noqa: F811
    result, calls, model = scenario(ha, monkeypatch, False)
    assert result["status"] == "succeeded", result
    mutations = [call for call in calls if call[1] == "POST"]
    assert len(mutations) == 3
    assert [call[3] for call in mutations[1:]] == [
        {"entity_id": "update.synthetic_1"}, {"entity_id": "update.synthetic_2"}]
    effects = [step for step in result["steps"] if step["kind"] == "effect"]
    assert len(effects) == 3 and all(s["result"]["effect_verified"] for s in effects)
    assert len([call for call in calls if call[0] == "http.verify"]) == 3
    assert len(model.inputs) == 7  # Semantic plus six actual next-step generations.
    discovery = json.dumps(model.inputs[3])  # Next step after both real discovery reads.
    assert "update.synthetic_1" in discovery and "update.synthetic_2" in discovery
    assert any(step["document"].get("arguments", {}).get("verification")
               for step in effects)
    assert all(step["result"]["verification_method"] == "prebound_read_predicate"
               for step in effects)


def test_uncertain_update_stops_without_redispatch_or_next_update(ha, monkeypatch):  # noqa: F811
    result, calls, model = scenario(ha, monkeypatch, True)
    assert result["status"] == "uncertain", result
    mutations = [call for call in calls if call[1] == "POST"]
    assert len(mutations) == 2
    assert mutations[-1][3] == {"entity_id": "update.synthetic_1"}
    assert not any(call[3] == {"entity_id": "update.synthetic_2"} for call in calls)
    assert len(model.inputs) == 5  # Semantic; services, states, backup, first update.



def test_tool_confirmation_is_repaired_without_user_input_or_extra_dispatch(ha, monkeypatch):  # noqa: F811
    result, calls, model = scenario(ha, monkeypatch, False, confirmations=1)
    assert result["status"] == "succeeded"
    assert len([step for step in result["steps"] if step["kind"] == "feedback"]) == 1
    assert len([call for call in calls if call[1] == "POST"]) == 3
    assert all(step["status"] != "awaiting_input" for step in result["steps"])
    assert len(model.inputs) == 8


def test_repeated_tool_confirmation_stops_bounded_without_target_changes(ha, monkeypatch):  # noqa: F811
    result, calls, model = scenario(ha, monkeypatch, False, confirmations=3)
    assert result["status"] == "failed"
    assert "lokale Planung" in result["summary"]
    assert "Zugriffsregeln" not in result["summary"]
    assert len([step for step in result["steps"] if step["kind"] == "feedback"]) == 2
    assert not [call for call in calls if call[1] == "POST"]
    assert len(model.inputs) == 4



def test_certain_admin_execution_confirmation_is_repaired_without_user_input(ha, monkeypatch):  # noqa: F811
    result, calls, model = scenario(
        ha, monkeypatch, False, confirmations=1, execution_question=True,
    )
    assert result["status"] == "succeeded"
    assert len([step for step in result["steps"] if step["kind"] == "feedback"]) == 1
    assert len([call for call in calls if call[1] == "POST"]) == 3
    assert len(model.inputs) == 8



def test_missing_automation_details_remain_a_real_question(ha, monkeypatch):  # noqa: F811
    result, calls, model = scenario(
        ha, monkeypatch, False, confirmations=1, essential_question=True,
        goal="Richte in Home Assistant eine Automation ein.",
    )
    assert result["status"] == "awaiting_input"
    assert "Auslöser" in result["summary"]
    assert not [step for step in result["steps"] if step["kind"] == "feedback"]
    assert not [call for call in calls if call[1] == "POST"]
    assert len(model.inputs) == 2
