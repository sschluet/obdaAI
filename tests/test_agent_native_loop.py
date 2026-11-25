"""Synthetic HA administration through the real API, worker, native SSE and codec."""

import asyncio
import json
from dataclasses import replace

import httpx
from hub import agent_reconcile
from hub import agent_runtime as runtime
from hub.agent_intent import RequestIntent, Requirement
from hub.agent_models import AgentJob
from hub.db import ProviderConfig, Run
from hub.provider_settings import seed
from hub.providers import Providers
from sqlalchemy import select
from test_agent_capability_runtime import start
from test_agent_native_transport import event, fragment

pytest_plugins = ["test_agent_capability_runtime"]

GOAL = "Bitte prüfe Home Assistant und spiele alle ausstehenden Update ein"


def scenario(
    ha,
    monkeypatch,
    tmp_path,
    *,
    uncertain=False,
    invalid_first=False,
    invalid_verification_first=False,
    projection_failure_first=False,
    projection_followup_failure=False,
    repeat_inventory=False,
    goal_outcome=True,
    remaining_update=False,
    require_backup=False,
    goal=GOAL,
):
    app, client, _, cfg, identifier, *_ = ha
    if require_backup:
        from test_agent_effect_prerequisites import RULE

        policy = client.get(f"/api/integrations/{identifier}/agent-policy").json()
        policy["rules"]["effect_prerequisites"] = [RULE]
        response = client.put(
            f"/api/integrations/{identifier}/agent-policy",
            headers=ha[2],
            json={
                "expected_revision": policy["revision"],
                "expected_profile_revision": 1,
                "rules": policy["rules"],
            },
        )
        assert response.status_code == 200, response.text
    cfg = replace(
        cfg,
        local_model="synthetic-native-model",
        local_base_url="http://127.0.0.1:11444/v1",
        local_allowed_ip="127.0.0.1",
        source_dir=str(tmp_path / "strictly-synthetic-inference"),
    )
    with app.state.sessions() as db:
        seed(db, cfg)
        provider = db.get(ProviderConfig, "local-default")
        config = json.loads(provider.config)
        config.update(model=cfg.local_model, base_url=cfg.local_base_url)
        provider.config = json.dumps(config)
        db.commit()
    model_requests, target_calls, model_failures = [], [], []
    backup, installed = False, False
    initial_projection = (
        [
            {
                "method": "GET",
                "path": "/api/config",
                "projection": {"fields": ["/version"], "limit": 1},
            }
        ]
        if projection_failure_first
        else []
    )
    directives = iter(
        [
            *initial_projection,
            {"method": "GET", "path": "/api/services"},
            {"method": "GET", "path": "/api/states"},
            *([{"method": "GET", "path": "/api/states"}] if repeat_inventory else []),
            {
                "method": "POST",
                "path": "/api/services/backup/create",
                "body": {"name": "synthetic-before-update"},
                "verification": {
                    "path": "/api/states/sensor.backup",
                    "expected": {"/body/state": "ready"},
                    "timeout_seconds": 1,
                    "interval_seconds": 1,
                },
            },
            {"method": "GET", "path": "/api/states"},
            {
                "method": "POST",
                "path": "/api/services/update/install",
                "body": {"entity_id": "update.synthetic"},
                "verification": {
                    "path": "/api/states/update.synthetic",
                    "expected": {"/body/state": "off"},
                    "timeout_seconds": 1,
                    "interval_seconds": 1,
                },
            },
            {"method": "GET", "path": "/api/states"},
            None,
        ]
    )
    original = httpx.AsyncClient

    def model(request):
        body = json.loads(request.content)
        model_requests.append(body)
        assert body["model"] == cfg.local_model
        if "response_format" in body:
            assert "tools" not in body and len(model_requests) == 1
            intent = RequestIntent(
                target_ids=[identifier],
                mode="admin",
                topic="system",
                requirements=[
                    Requirement(kind="system", integration_id=identifier),
                    Requirement(kind="effect_postcondition", integration_id=identifier),
                ],
            )
            if goal_outcome:
                from hub.agent_intent import EntityOutcome

                intent.requirements[-1].outcome = EntityOutcome(
                    domain="update",
                    state="off",
                    scope="all_observed",
                    selection_state="on",
                    attribute_from_initial={"installed_version": "latest_version"},
                )
            else:
                intent.requirements.append(
                    Requirement(
                        kind="entity_states",
                        domain="update",
                        integration_id=identifier,
                    )
                )
            return httpx.Response(
                200, text=event({"content": intent.model_dump_json()}) + "data: [DONE]\n\n"
            )
        assert body["tool_choice"] == "auto" and "temperature" not in body
        # Even the first native step sees the real bootstrap receipt in the
        # provider's conversation protocol, rather than a second opaque history.
        messages = body["messages"][2:]
        if len(model_requests) == 2:
            assert messages
        # Tight later contexts may retain a derived observation instead of
        # reconstructing calls whose arguments were already clipped.
        assert len(messages) % 2 == 0
        for call, receipt in zip(messages[::2], messages[1::2], strict=True):
            assert call["role"] == "assistant" and len(call["tool_calls"]) == 1
            assert receipt["role"] == "tool"
            assert receipt["tool_call_id"] == call["tool_calls"][0]["id"]
            assert json.loads(receipt["content"])["_obdaai_receipt"]["model_view_only"]
        if invalid_first and len(model_requests) == 2:
            return httpx.Response(
                200, text=event(fragment("unknown_function", "{}")) + "data: [DONE]\n\n"
            )
        if invalid_verification_first and len(model_requests) == 2:
            name = next(
                t["function"]["name"]
                for t in body["tools"]
                if t["function"]["name"].endswith("_http_project")
            )
            arguments = {
                "arguments": {
                    "method": "GET",
                    "path": "/api/config",
                    "filter_mode": "none",
                    "filter_field": "",
                    "filter_value": None,
                    "verification": {
                        "path": "/api/config",
                        "expected": {"/body/version": "synthetic"},
                    },
                }
            }
            return httpx.Response(
                200, text=event(fragment(name, json.dumps(arguments))) + "data: [DONE]\n\n"
            )
        if invalid_verification_first and len(model_requests) == 3:
            data = json.loads(body["messages"][1]["content"])
            feedback = [row for row in data["history"] if row["kind"] == "feedback"]
            diagnostics = feedback[-1]["document"]["issues"][0]["diagnostics"]
            assert "schema_type:verification:null" in diagnostics
        if invalid_first and len(model_requests) == 3:
            data = json.loads(body["messages"][1]["content"])
            feedback = [row for row in data["history"] if row["kind"] == "feedback"]
            assert feedback[-1]["document"]["issues"] == [
                {"type": "native_call_invalid", "diagnostics": ["native_unknown_function"]}
            ]
        if projection_failure_first and len(model_requests) == 3:
            data = json.loads(body["messages"][1]["content"])
            assert data["read_recovery"]["recovery_kind"] == "projection"
            assert data["read_recovery"]["needs_alternative"]
            assert data["read_only"] and not data["allow_finish"]
        directive = next(directives)
        names = [row["function"]["name"] for row in body["tools"]]
        if directive is None:
            final = json.loads(body["messages"][1]["content"])
            assert final["remaining_effects"] == 0 and final["read_only"]
            assert not any(n.endswith("_http_verify") for n in names)
            assert '"POST"' not in json.dumps(
                [row["function"]["parameters"] for row in body["tools"]]
            )
        if directive is None and remaining_update:
            assert "finish_run" not in names and "stop_run" in names
            assert final["execution_state"]["phase"] == "blocked"
            outcomes = final["execution_state"]["outcomes"]
            if goal_outcome:
                assert outcomes[0]["remaining_count"] == 1
            else:
                assert final["execution_state"]["completion_binding_missing"] == [identifier]
            name, arguments = "stop_run", {"message": "Synthetic goal remains incomplete."}
        else:
            if directive is None:
                name, arguments = "finish_run", {"message": "Synthetic backup verified."}
            elif directive.get("projection") is not None:
                projection = directive["projection"]
                pointer, prefix = projection.get("where_pointer"), projection.get("where_prefix")
                mode = "none" if pointer is None else "prefix" if prefix is not None else "equals"
                name = next(n for n in names if n.endswith("_http_project"))
                arguments = {
                    "arguments": {k: v for k, v in directive.items() if k != "projection"}
                    | {
                        "items_path": projection.get("items_path", ""),
                        "fields": projection.get("fields", []),
                        "limit": projection.get("limit", 30),
                        "filter_mode": mode,
                        "filter_field": pointer if pointer is not None else "",
                        "filter_value": prefix
                        if mode == "prefix"
                        else projection.get("where_equals"),
                    }
                }
            elif directive["method"] == "GET":
                name = next(n for n in names if n.endswith("_http_read"))
                arguments = {
                    "arguments": {k: v for k, v in directive.items() if k in {"path", "query"}}
                }
            else:
                name = next(n for n in names if n.endswith("_http_change"))
                arguments = {"arguments": directive}
        text = json.dumps(arguments)
        midpoint = len(text) // 2
        return httpx.Response(
            200,
            text=event(fragment(name, text[:midpoint]))
            + event(fragment(arguments=text[midpoint:]))
            + "data: [DONE]\n\n",
        )

    def checked_model(request):
        try:
            return model(request)
        except (AssertionError, StopIteration) as error:
            import traceback

            body = json.loads(request.content)
            model_failures.append(
                {
                    "type": type(error).__name__,
                    "line": traceback.extract_tb(error.__traceback__)[-1].lineno,
                    "request_count": len(model_requests),
                    "functions": [t["function"]["name"] for t in body.get("tools", [])],
                    "response_format": "response_format" in body,
                    "goal_evidence": json.loads(body["messages"][1]["content"]).get(
                        "goal_evidence"
                    ),
                }
            )
            raise

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(checked_model)),
    )
    monkeypatch.setattr(
        Providers,
        "_target",
        lambda *_: ("http://127.0.0.1/v1/chat/completions", {"Host": "synthetic-model"}, {}, ""),
    )

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        nonlocal backup, installed
        before_send()
        assert secret == "synthetic-write-token"
        target_calls.append((tool, args.get("method", "GET"), args["path"]))
        if tool == "http.verify":
            passed = backup if args["path"].endswith("sensor.backup") else installed
            return {
                "http_status": 200,
                "verification_passed": passed,
                "body": {"state": "ready" if args["path"].endswith("sensor.backup") else "off"},
            }
        if args["method"] == "POST":
            assert args["verification"] is not None
            if args["path"].endswith("backup/create"):
                backup = True
            else:
                assert backup and args["body"] == {"entity_id": "update.synthetic"}
                if uncertain:
                    raise TimeoutError("Synthetic lost update acknowledgement")
                installed = True
            return {"http_status": 200, "body": {}, "effect_verified": False}
        payload = {"message": "API running."}
        if projection_failure_first and args["path"] == "/api/config":
            return {
                "http_status": 200,
                "body": {"version": "synthetic"},
                "projection_error": "Synthetic list projection does not match object",
                "effect_verified": False,
            }
        if projection_followup_failure and args["path"] == "/api/services":
            return {"http_status": 403, "body": {}, "effect_verified": False}
        if args["path"] == "/api/services":
            payload = [
                {"domain": "backup", "services": {"create": {"fields": {"name": {}}}}},
                {"domain": "update", "services": {"install": {"fields": {"entity_id": {}}}}},
            ]
        elif args["path"] == "/api/states":
            payload = [
                {
                    "entity_id": "update.synthetic",
                    "state": "off" if installed else "on",
                    "attributes": {
                        "installed_version": "2" if installed else "1",
                        "latest_version": "2",
                    },
                }
            ]
            if remaining_update:
                payload.append(
                    {
                        "entity_id": "update.second",
                        "state": "on",
                        "attributes": {
                            "installed_version": "3",
                            "latest_version": "4",
                        },
                    }
                )
            if args.get("projection") is not None:
                from hub.agent_context import project

                payload = project(payload, args["projection"])
        return {"http_status": 200, "body": payload, "effect_verified": False}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(agent_reconcile, "invoke", invoke)
    job_id = start(ha, goal, research_allowed=False)
    if not goal_outcome:
        # This case exercises an explicit legacy semantic contract, not a shortcut.
        with app.state.sessions() as db:
            job = db.get(AgentJob, job_id)
            job.bindings = json.dumps({**json.loads(job.bindings), "intent": None})
            db.commit()
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, Providers(cfg), job_id))
    result = client.get("/api/agent-runs/" + job_id).json()
    assert not model_failures, model_failures
    before_restart = (len(model_requests), list(target_calls))
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, Providers(cfg), job_id))
    assert (len(model_requests), target_calls) == before_restart
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert json.loads(job.bindings)["intent"]["mode"] == "admin"
        assert not json.loads(job.bindings).get("native_fallback_used")
        runs = list(db.scalars(select(Run).where(Run.conversation_id == job.model_conversation_id)))
        assert all(run.provider == "local" for run in runs)
        for run in runs:
            snapshot = json.loads(run.context_snapshot)
            if snapshot["agent_generation"].get("native_plan"):
                assert json.loads(run.routing_trace)["native_provider"]["model"] == cfg.local_model
    return result, model_requests, target_calls


def test_true_native_general_administration_loop_reads_backs_up_updates_and_verifies(
    ha,
    monkeypatch,
    tmp_path,
):
    result, requests, calls = scenario(ha, monkeypatch, tmp_path)
    assert result["status"] == "succeeded", json.dumps(result, ensure_ascii=False)
    assert len(requests) == 7 and len([r for r in requests if "tools" in r]) == 6
    assert [call[2] for call in calls if call[1] == "POST"] == [
        "/api/services/backup/create",
        "/api/services/update/install",
    ]
    effects = [step for step in result["steps"] if step["kind"] == "effect"]
    assert len(effects) == 2 and all(step["result"]["effect_verified"] for step in effects)
    assert len([call for call in calls if call[0] == "http.verify"]) == 2
    assert not [step for step in result["steps"] if step["kind"] in {"feedback", "error"}]
    assert all(
        step["document"].get("protocol") == "native"
        for step in result["steps"]
        if step["kind"] == "model" and not step["document"].get("intent_interpretation")
    )


def test_native_general_loop_stops_on_uncertain_update_without_native_or_target_replay(
    ha,
    monkeypatch,
    tmp_path,
):
    result, requests, calls = scenario(ha, monkeypatch, tmp_path, uncertain=True)
    assert result["status"] == "uncertain", result
    assert len(requests) == 6 and len([r for r in requests if "tools" in r]) == 5
    assert len([call for call in calls if call[2] == "/api/services/update/install"]) == 1
    assert not [step for step in result["steps"] if step["kind"] == "feedback"]


def test_native_unknown_function_gets_safe_feedback_before_any_target_dispatch(
    ha,
    monkeypatch,
    tmp_path,
):
    result, requests, calls = scenario(ha, monkeypatch, tmp_path, invalid_first=True)
    assert result["status"] == "succeeded", json.dumps(result, ensure_ascii=False)
    assert len(requests) == 8
    feedback = [step for step in result["steps"] if step["kind"] == "feedback"]
    assert len(feedback) == 1 and feedback[0]["document"]["issues"] == [
        {"type": "native_call_invalid", "diagnostics": ["native_unknown_function"]}
    ]
    failed_models = [
        step for step in result["steps"] if step["kind"] == "model" and step["status"] == "failed"
    ]
    assert len(failed_models) == 1
    assert len([call for call in calls if call[1] == "POST"]) == 2
    assert all(call[0] != "unknown_function" for call in calls)


def test_native_admin_recovers_projection_before_authorized_backup_and_update(
    ha,
    monkeypatch,
    tmp_path,
):
    result, requests, calls = scenario(ha, monkeypatch, tmp_path, projection_failure_first=True)
    assert result["status"] == "succeeded", json.dumps(result, ensure_ascii=False)
    assert len(requests) == 8
    failed = [
        step for step in result["steps"] if step["kind"] == "read" and step["status"] == "failed"
    ]
    assert len(failed) == 1 and failed[0]["result"]["failure_phase"] == "projection"
    assert failed[0]["result"]["http_status"] == 200
    assert len([call for call in calls if call[2] == "/api/config"]) == 1
    assert len([call for call in calls if call[1] == "POST"]) == 2
    assert not [step for step in result["steps"] if step["kind"] in {"input", "approval", "error"}]


def test_invalid_read_verification_gets_precise_feedback_without_target_dispatch(
    ha,
    monkeypatch,
    tmp_path,
):
    result, requests, calls = scenario(
        ha,
        monkeypatch,
        tmp_path,
        invalid_verification_first=True,
    )
    assert result["status"] == "succeeded", json.dumps(result, ensure_ascii=False)
    assert len(requests) == 8
    assert len([step for step in result["steps"] if step["kind"] == "feedback"]) == 1
    assert not [call for call in calls if call[2] == "/api/config"]
    assert len([call for call in calls if call[1] == "POST"]) == 2


def test_native_projection_correction_second_failed_read_stops_before_any_effect(
    ha,
    monkeypatch,
    tmp_path,
):
    result, requests, calls = scenario(
        ha,
        monkeypatch,
        tmp_path,
        projection_failure_first=True,
        projection_followup_failure=True,
    )
    assert result["status"] == "failed", result
    assert len(requests) == 3
    assert (
        len(
            [
                step
                for step in result["steps"]
                if step["kind"] == "read" and step["status"] == "failed"
            ]
        )
        == 2
    )
    assert not [call for call in calls if call[1] == "POST"]
