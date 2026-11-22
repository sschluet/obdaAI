"""Synthetic API/worker acceptance for capability-first administration and access checks."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from hub import agent_reconcile
from hub import agent_runtime as runtime
from hub.agent_intent import RequestIntent, Requirement
from hub.agent_models import AgentJob, AgentPolicy
from hub.agent_tools import Rules, validate_tool
from hub.integrations import Integration
from hub.provider_settings import encrypt
from test_actions import gateway, set_pause  # noqa: F401
from test_agents import agent  # noqa: F401
from test_integration_writes import writes  # noqa: F401


@pytest.fixture
def ha(agent):  # noqa: F811
    app, client, headers, cfg, identifier, chat, state, effects = agent
    with app.state.sessions() as db:
        target = db.get(Integration, identifier)
        target.kind, target.name = "home_assistant", "Synthetic Home Assistant"
        target.config = json.dumps({"kind": "home_assistant", "url": "https://ha.example.test"})
        db.commit()
    rules = Rules(
        enabled=True, autonomous=True, private_data_to_target=True,
        http_prefixes=["/api/"], http_methods=["GET", "POST", "PATCH"],
        ha_websocket_prefixes=["config/", "get_config"],
        production_ha_approved=True, max_steps=8, max_effects=2,
    )
    response = client.put(
        f"/api/integrations/{identifier}/agent-policy",
        json={"expected_revision": 1, "expected_profile_revision": 1,
              "rules": rules.model_dump()}, headers=headers,
    )
    assert response.status_code == 200, response.text
    return agent


def start(ha, goal="Kannst Du auf Home Assistant zugreifen?", *, research_allowed=True):
    app, client, headers, cfg, identifier, chat, state, effects = ha
    response = client.post(
        f"/api/conversations/{chat}/agent-runs",
        json={"request_id": str(uuid4()), "goal": goal, "research_allowed": research_allowed},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def execute(ha, job_id):
    app, client, headers, cfg, *_ = ha
    planner = runtime.generate

    async def semantic_then_planner(*args):
        data = args[-1]
        if data.get("intent_schema"):
            with app.state.sessions() as db:
                job = db.get(AgentJob, job_id)
                administrative = "Entitätsregistrierung" in job.goal
            return RequestIntent(
                target_ids=[ha[4]], mode="admin" if administrative else "observe",
                topic="system", origin="semantic",
                requirements=[Requirement(kind="effect_postcondition" if administrative
                                          else "system", integration_id=ha[4])],
            ).model_dump()
        return await planner(*args)

    runtime.generate = semantic_then_planner
    try:
        asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    finally:
        runtime.generate = planner
    response = client.get("/api/agent-runs/" + job_id)
    assert response.status_code == 200, response.text
    return response.json()


def no_planning(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("A pure access question must not invoke model or research")

    monkeypatch.setattr(runtime, "generate", forbidden)
    monkeypatch.setattr(runtime, "research", forbidden)


def transport(monkeypatch, outcome=200):
    sent = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        assert config["kind"] == "home_assistant" and secret == "synthetic-write-token"
        assert tool == "http" and args["method"] == "GET"
        assert args["body"] is None and args["query"] == {}
        sent.append((tool, dict(args)))
        if outcome == "timeout":
            raise httpx.ConnectTimeout("SYNTHETIC-PRIVATE-TOKEN https://private.example.invalid")
        body = ([{"domain": "light", "services": {"turn_on": {"fields": {}}}}]
                if args["path"] == "/api/services" else {"message": "API running."})
        return {"http_status": outcome, "body": body, "effect_verified": False}

    monkeypatch.setattr(runtime, "invoke", invoke)
    return sent


@pytest.mark.parametrize(
    "goal", ["Kannst Du auf Home Assistant zugreifen?", "Hast du Zugriff auf HA?",
             "Can you access Synthetic Home Assistant?", "Is HA reachable?"],
)
def test_access_question_is_one_authenticated_read_without_planning_or_confirmation(
    ha, monkeypatch, goal
):
    no_planning(monkeypatch)
    sent = transport(monkeypatch)
    job_id = start(ha, goal)
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert json.loads(job.bindings)["read_only"] is True
        assert job.research_allowed is False and job.max_effects == 0
    result = execute(ha, job_id)
    assert result["status"] == "observed" and "Anmeldung funktioniert" in result["summary"]
    assert len(sent) == 1 and sent[0][1]["path"] == "/api/"
    assert [(s["kind"], s["status"]) for s in result["steps"]] == [("read", "succeeded")]
    assert result["steps"][0]["document"]["capability_inspection"] is True
    assert not result["steps"][0]["approved"] and not ha[-1]
    execute(ha, job_id)
    assert len(sent) == 1  # The same completed job cannot repeat even its fixed read.


@pytest.mark.parametrize(
    ("outcome", "category", "summary"),
    [(401, "authentication_failed", "Anmeldung"),
     (403, "authorization_failed", "verweigert"),
     ("timeout", "timeout", "rechtzeitig")],
)
def test_failed_access_read_is_explained_and_does_not_block_a_new_request(
    ha, monkeypatch, outcome, category, summary
):
    no_planning(monkeypatch)
    sent = transport(monkeypatch, outcome)
    failed = execute(ha, start(ha))
    assert failed["status"] == "failed" and summary in failed["summary"]
    assert "nicht eindeutig" not in failed["summary"]
    assert len(sent) == 1 and not ha[-1]
    assert failed["steps"][0]["kind"] == "read"
    assert failed["steps"][0]["status"] == "failed"
    assert failed["steps"][0]["result"]["failure_category"] == category
    assert "SYNTHETIC-PRIVATE-TOKEN" not in json.dumps(failed)
    assert "private.example.invalid" not in json.dumps(failed)
    second_sent = transport(monkeypatch, 200)
    next_job = start(ha)
    assert next_job != failed["id"]
    assert execute(ha, next_job)["status"] == "observed"
    assert len(second_sent) == 1 and not ha[-1]


def test_http_success_without_actual_ha_api_shape_does_not_claim_access(ha, monkeypatch):
    no_planning(monkeypatch)

    def unrelated(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        return {"http_status": 200, "body": {"message": "Some other service"}}

    monkeypatch.setattr(runtime, "invoke", unrelated)
    result = execute(ha, start(ha))
    assert result["status"] == "failed" and "nicht bestätigt" in result["summary"]
    assert "Anmeldung funktioniert" not in result["summary"]


def test_general_administration_inspects_before_model_and_exposes_verified_capabilities(
    ha, monkeypatch
):
    sent = transport(monkeypatch)
    model_data = []

    async def model(factory, cfg, providers, job_id, instruction, data):
        model_data.append(data)
        assert len(sent) == len(model_data) and sent[0][1]["path"] == "/api/"
        capabilities = data["interfaces"][0]["capabilities"]
        assert capabilities["inspection"]["arguments"]["path"] == "/api/"
        assert "config/verify_connection" not in capabilities["operations"]["websocket_types"]
        assert capabilities["operations"]["http_methods"] == ["GET"]
        assert data["history"][0]["document"]["capability_inspection"] is True
        assert "research" in data["tools"]
        if len(model_data) == 1:
            return {"kind": "tool", "message": "Verfügbare Dienste lesen",
                    "integration_id": ha[4], "tool": "http",
                    "arguments": {"method": "GET", "path": "/api/services"}}
        assert data["history"][-1]["result"]["body"][0]["domain"] == "light"
        return {"kind": "finish", "message": "Verbindung geprüft; Lichtdienste gefunden."}

    async def forbidden_research(*args, **kwargs):
        raise AssertionError(
            "Initial native inspection should replace speculative upfront research"
        )

    monkeypatch.setattr(runtime, "generate", model)
    monkeypatch.setattr(runtime, "research", forbidden_research)
    job_id = start(ha, "Prüfe Home Assistant und ermittle die verfügbaren Dienste.")
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert json.loads(job.bindings)["read_only"] is False and job.max_effects == 2
    result = execute(ha, job_id)
    assert result["status"] == "observed" and len(model_data) == 2
    assert [args["path"] for tool, args in sent] == ["/api/", "/api/services"]
    assert not ha[-1]


@pytest.mark.parametrize("verified", [False, True])
def test_advanced_authorized_websocket_operation_remains_available_with_effect_boundaries(
    ha, monkeypatch, verified
):
    calls = []
    turns = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        calls.append((tool, dict(args)))
        if tool == "ha.websocket":
            assert args["type"] == "config/entity_registry/list"
            assert args["parameters"] == {}
            return {"response": [{"entity_id": "sensor.synthetic"}], "effect_verified": False}
        if tool == "http.verify":
            assert verified and args["path"] == "/api/states/sensor.synthetic"
            return {"http_status": 200, "body": {"entity_id": "sensor.synthetic"},
                    "verification_passed": True, "effect_verified": False}
        assert tool == "http" and args["method"] == "GET" and args["path"] == "/api/"
        return {"http_status": 200, "body": {"message": "API running."},
                "effect_verified": False}

    async def model(factory, cfg, providers, job_id, instruction, data):
        turns.append(data)
        if len(turns) == 1:
            capabilities = data["interfaces"][0]["capabilities"]
            # Discovery hints are not an exhaustive replacement for the human's
            # authorized administration scope and its researched advanced APIs.
            assert "config/entity_registry/list" not in (
                capabilities["operations"]["websocket_types"]
            )
            arguments = {"type": "config/entity_registry/list", "parameters": {}}
            if verified:
                arguments["verification"] = {
                    "path": "/api/states/sensor.synthetic",
                    "expected": {"/body/entity_id": "sensor.synthetic"},
                }
            return {"kind": "tool", "message": "Entitätsregistrierung lesen",
                    "integration_id": ha[4], "tool": "ha.websocket", "arguments": arguments}
        return {"kind": "finish", "message": "Entitätsregistrierung geprüft."}

    monkeypatch.setattr(runtime, "generate", model)
    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(agent_reconcile, "invoke", invoke)
    result = execute(ha, start(ha, "Prüfe die Home-Assistant-Entitätsregistrierung."))
    assert result["status"] == ("succeeded" if verified else "unverified")
    assert len(turns) == 2
    assert [tool for tool, _ in calls] == (
        ["http", "ha.websocket", "http.verify"] if verified else ["http", "ha.websocket"]
    )
    effect = next(step for step in result["steps"] if step["kind"] == "effect")
    assert effect["result"]["effect_verified"] is verified
    assert not effect["approved"]  # Existing bounded autonomy, no new confirmation.
    assert not any(step["kind"] == "feedback" for step in result["steps"])


def test_revocation_during_inspection_setup_prevents_credential_transmission(ha, monkeypatch):
    no_planning(monkeypatch)
    sent = []

    def revoke_before_send(cfg, config, secret, tool, args, rules, before_send):
        with ha[0].state.sessions() as db:
            db.get(AgentPolicy, ha[4]).revision += 1
            db.commit()
        before_send()
        sent.append("must not transmit")
        return {"http_status": 200, "body": {"message": "API running."}}

    monkeypatch.setattr(runtime, "invoke", revoke_before_send)
    result = execute(ha, start(ha))
    assert result["status"] == "failed" and not sent and not ha[-1]
    assert not any(step["kind"] == "effect" for step in result["steps"])


def test_failed_known_metadata_websocket_response_is_not_a_successful_observation(ha, monkeypatch):
    calls = []
    turns = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        calls.append(tool)
        if tool == "ha.websocket":
            assert args["type"] == "get_config" and not args["parameters"]
            return {"success": False, "error": {"message": "SYNTHETIC-PRIVATE-ERROR"}}
        return {"http_status": 200, "body": {"message": "API running."}}

    async def model(*args):
        turns.append(args)
        assert len(turns) == 1, "A failed metadata read must terminate without invented success"
        return {"kind": "tool", "message": "Konfiguration lesen", "integration_id": ha[4],
                "tool": "ha.websocket", "arguments": {"type": "get_config", "parameters": {}}}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha, "Lies die Home-Assistant-Konfiguration."))
    assert result["status"] == "failed" and calls == ["http", "ha.websocket"]
    assert not any(step["kind"] == "effect" for step in result["steps"])
    failed = result["steps"][-1]
    assert failed["kind"] == "read" and failed["status"] == "failed"
    assert failed["result"]["failure_category"] == "protocol_error"
    assert "SYNTHETIC-PRIVATE-ERROR" not in json.dumps(result)


def test_interrupted_read_preserves_uncertainty_of_prior_unverified_effect(ha, monkeypatch):
    no_planning(monkeypatch)
    calls = []
    monkeypatch.setattr(runtime, "invoke", lambda *args: calls.append("must not transmit"))
    job_id = start(ha, "Prüfe Home Assistant nach der angeforderten Änderung.")
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        profiles = runtime.gate(db, ha[3], job)
        profile, rules, _ = profiles[ha[4]]
        effect_args, effect = validate_tool(profile.kind, rules, "http", {
            "method": "POST", "path": "/api/services/light/turn_on",
            "body": {"entity_id": "light.synthetic"},
        })
        assert effect
        previous = runtime.record(db, job, "effect", {
            "kind": "tool", "integration_id": ha[4], "tool": "http",
            "arguments": effect_args, "message": "Bereits bestätigte Aktion ohne Nachprüfung",
        })
        previous.status, previous.result = "succeeded", json.dumps({"effect_verified": False})
        read_args, effective = validate_tool(profile.kind, rules, "http", {
            "method": "GET", "path": "/api/states/light.synthetic",
        })
        assert not effective
        interrupted = runtime.record(db, job, "read", {
            "kind": "tool", "integration_id": ha[4], "tool": "http",
            "arguments": read_args, "message": "Unterbrochene Nachprüfung",
        })
        interrupted.status = "dispatching"
        db.commit()
    result = execute(ha, job_id)
    assert result["status"] == "uncertain" and not calls
    assert result["steps"][0]["status"] == "succeeded"
    assert not result["steps"][0]["result"]["effect_verified"]
    assert result["steps"][1]["status"] == "failed"
    execute(ha, job_id)
    assert not calls


def single_step_policy(ha, identifier, expected_revision):
    with ha[0].state.sessions() as db:
        current = db.get(AgentPolicy, ha[4])
        rules = Rules.model_validate_json(current.rules)
        rules.max_steps = 1
    response = ha[1].put(
        f"/api/integrations/{identifier}/agent-policy",
        json={"expected_revision": expected_revision, "expected_profile_revision": 1,
              "rules": rules.model_dump()}, headers=ha[2],
    )
    assert response.status_code == 200, response.text


def test_multiple_access_profiles_respect_each_targets_single_step_budget(ha, monkeypatch):
    no_planning(monkeypatch)
    single_step_policy(ha, ha[4], 2)
    with ha[0].state.sessions() as db:
        second = Integration(kind="home_assistant", name="Second HA", enabled=True,
                             writes_enabled=True, config=json.dumps({
                                 "kind": "home_assistant", "url": "https://ha-two.example.test",
                             }))
        db.add(second)
        db.flush()
        identifier = second.id
        second.encrypted_secret = encrypt(
            ha[3], "integration:" + identifier, "synthetic-write-token"
        )
        db.commit()
    single_step_policy(ha, identifier, 0)
    response = ha[1].put(
        f"/api/integration-bindings/conversation/{ha[5]}",
        json={"expected_revision": 1, "integration_ids": [ha[4], identifier],
              "selection_mode": "manual"}, headers=ha[2],
    )
    assert response.status_code == 200, response.text
    calls = transport(monkeypatch)
    job_id = start(ha)
    result = execute(ha, job_id)
    assert result["status"] == "observed" and len(calls) == 2 and not ha[-1]
    operations = [step for step in result["steps"] if step["kind"] == "read"]
    assert len(operations) == 2
    assert {step["document"]["integration_id"] for step in operations} == {ha[4], identifier}


def test_single_step_administration_reserves_budget_for_the_requested_operation(ha, monkeypatch):
    single_step_policy(ha, ha[4], 2)
    calls = transport(monkeypatch)
    turns = []

    async def model(*args):
        turns.append(args)
        if args[-1].get("summarize_only"):
            assert calls and args[-1]["tools"] == {}
            return {"kind": "finish", "message": "Dienste erfolgreich gelesen."}
        assert not calls  # No automatic /api/ bootstrap consumed the one permitted operation.
        return {"kind": "tool", "message": "Dienste lesen", "integration_id": ha[4],
                "tool": "http", "arguments": {"method": "GET", "path": "/api/services"}}

    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha, "Lies die verfügbaren Home-Assistant-Dienste.",
                              research_allowed=False))
    assert [args["path"] for tool, args in calls] == ["/api/services"]
    assert len(turns) == 2 and result["status"] == "observed"
    operation_steps = [step for step in result["steps"] if step["kind"] in {"read", "effect"}]
    assert len(operation_steps) == 1 and operation_steps[0]["kind"] == "read"
    assert not operation_steps[0]["document"].get("capability_inspection")
