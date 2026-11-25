"""Real worker/provider HTTP envelopes preserve private schemas and semantic role limits."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from hub import agent_runtime as runtime
from hub.agent_intent import RequestIntent, Requirement, semantic_request
from hub.agent_models import AgentJob
from hub.db import ProviderConfig, Run
from hub.provider_settings import seed
from hub.providers import Providers
from hub.request_interpretation import interpret
from sqlalchemy import select
from test_agent_capability_runtime import start
from test_agent_native_transport import event

pytest_plugins = ["test_agent_capability_runtime"]
GOAL = "Kannst Du auf Home Assistant zugreifen?"


def setup(ha, monkeypatch, handler):
    app, _, _, cfg, identifier, *_ = ha
    cfg = replace(
        cfg,
        local_base_url="http://127.0.0.1:11444/v1",
        local_allowed_ip="127.0.0.1",
        local_model="synthetic-role-model",
    )
    with app.state.sessions() as db:
        seed(db, cfg)
        row = db.get(ProviderConfig, "local-default")
        config = json.loads(row.config)
        config.update(model=cfg.local_model, base_url=cfg.local_base_url, output_tokens=1500)
        row.config = json.dumps(config)
        db.commit()
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(handler),
            **kw,
        ),
    )
    monkeypatch.setattr(
        Providers,
        "_target",
        lambda *_: (
            "http://127.0.0.1/v1/chat/completions",
            {},
            {},
            "",
        ),
    )
    job_id = start(ha, goal=GOAL, research_allowed=False)
    with app.state.sessions() as db:
        job = db.get(AgentJob, job_id)
        job.bindings = json.dumps({**json.loads(job.bindings), "intent": None})
        db.commit()
    return cfg, job_id


def intent(identifier, *, invalid=False):
    return RequestIntent(
        mode="admin" if invalid else "observe",
        topic="connection",
        target_ids=[identifier],
        requirements=[Requirement(kind="connection", integration_id=identifier)],
    ).model_dump(mode="json")


def test_worker_and_api_send_same_bounded_intent_without_visible_authority_schema(ha, monkeypatch):
    bodies = []
    identifier = ha[4]

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, text=event({"content": json.dumps(intent(identifier))}) + "data: [DONE]\n\n"
        )

    cfg, job_id = setup(ha, monkeypatch, handler)
    profiles = {identifier: SimpleNamespace(kind="home_assistant", name="Synthetic Home Assistant")}
    request = semantic_request(GOAL, profiles)
    asyncio.run(
        runtime.generate(
            ha[0].state.sessions,
            cfg,
            Providers(cfg),
            job_id,
            request["instruction"],
            {**request["data"], "intent_schema": request["schema"]},
        )
    )
    asyncio.run(interpret(ha[0].state.sessions, cfg, GOAL, profiles))
    assert len(bodies) == 2
    for body in bodies:
        assert body["max_tokens"] == 768 and body["enable_thinking"] is False
        visible = json.loads(body["messages"][1]["content"])
        assert "intent_schema" not in visible
        assert visible == request["data"]
        assert body["response_format"]["json_schema"]["schema"] == request["schema"]
    with ha[0].state.sessions() as db:
        run = db.scalar(
            select(Run).where(Run.conversation_id == db.get(AgentJob, job_id).model_conversation_id)
        )
        snapshot = json.loads(run.context_snapshot)
        assert snapshot["agent_generation"]["intent_schema"] == request["schema"]
        assert "intent_schema" not in json.loads(snapshot["parts"][1]["content"])
        assert json.loads(run.routing_trace)["answer_limits"]["effective_output_tokens"] == 768
    # Ordinary local execution keeps the adaptive configured allowance.
    asyncio.run(
        runtime.generate(
            ha[0].state.sessions,
            cfg,
            Providers(cfg),
            job_id,
            "Synthetic summary",
            {"summarize_only": True},
        )
    )
    assert bodies[-1]["max_tokens"] == 1500


@pytest.mark.parametrize("failure", ["invalid", "malformed", "twice", "revoked", "http"])
def test_worker_has_one_durable_semantic_repair_with_current_gates(ha, monkeypatch, failure):
    bodies, targets = [], []
    cfg = None

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert "intent_schema" not in json.loads(body["messages"][1]["content"])
        assert body["max_tokens"] == 768
        if failure == "http":
            return httpx.Response(401, text="SYNTHETIC_PRIVATE_FAILURE")
        if failure == "revoked" and len(bodies) == 1:
            with ha[0].state.sessions() as db:
                db.get(ProviderConfig, "local-default").enabled = False
                db.commit()
        if len(bodies) == 1 and failure == "malformed":
            text = '{"truncated":'
        else:
            text = json.dumps(intent(ha[4], invalid=len(bodies) == 1 or failure == "twice"))
        return httpx.Response(200, text=event({"content": text}) + "data: [DONE]\n\n")

    cfg, job_id = setup(ha, monkeypatch, handler)

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        targets.append(args)
        assert args["method"] == "GET"
        return {"http_status": 200, "body": {"message": "API running."}}

    monkeypatch.setattr(runtime, "invoke", invoke)
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, cfg, Providers(cfg), job_id))
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        steps = runtime.steps(db, job_id)
        feedback = [s for s in steps if s.kind == "feedback"]
        assert not any(s.kind == "effect" for s in steps)
        if failure in {"invalid", "malformed"}:
            assert job.status == "observed" and len(bodies) == 2 and len(targets) == 1, (
                job.summary,
                [(b.get("max_tokens"), "response_format" in b, "tools" in b) for b in bodies],
                [(s.kind, s.status, json.loads(s.result)) for s in steps],
            )
            assert len(feedback) == 1
            second = json.loads(bodies[1]["messages"][1]["content"])
            issue = second["semantic_feedback"]["issue"]
            assert issue == (
                "semantic_contract_invalid"
                if failure == "malformed"
                else "semantic_postcondition_missing"
            )
        else:
            assert job.status == "failed" and not targets
            assert len(bodies) == (2 if failure == "twice" else 1)
        assert "SYNTHETIC_PRIVATE_FAILURE" not in job.summary


def test_completed_second_semantic_run_before_binding_never_dispatches_third_on_restart(
    ha, monkeypatch
):
    sent = []
    cfg, job_id = setup(ha, monkeypatch, lambda request: sent.append(True))
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        for _ in range(2):
            step = runtime.record(db, job, "model", {"intent_interpretation": True})
            step.status, step.result = "succeeded", json.dumps(intent(ha[4]))
        step = runtime.record(
            db,
            job,
            "feedback",
            {
                "rejected_decision": {"reason": "semantic_intent_invalid"},
            },
        )
        step.status = "succeeded"
        db.commit()
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, cfg, Providers(cfg), job_id))
    assert not sent
    with ha[0].state.sessions() as db:
        assert db.get(AgentJob, job_id).status == "failed"
        assert len([s for s in runtime.steps(db, job_id) if s.kind == "model"]) == 2


def test_worker_semantic_repair_uses_original_job_deadline(ha, monkeypatch):
    import time

    bodies = []

    async def handler(request):
        bodies.append(json.loads(request.content))
        await asyncio.sleep(0.65)
        answer = intent(ha[4], invalid=len(bodies) == 1)
        return httpx.Response(200, text=event({"content": json.dumps(answer)}) + "data: [DONE]\n\n")

    cfg, job_id = setup(ha, monkeypatch, handler)
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        job.created, job.timeout_seconds = time.time(), 1
        db.commit()
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, cfg, Providers(cfg), job_id))
    assert len(bodies) == 2
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert job.status == "failed"
        assert not any(s.kind in {"read", "effect"} for s in runtime.steps(db, job_id))
