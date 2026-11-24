"""Native generation keeps the shared durable runs, authority and fallback limits."""

import asyncio
import json
from dataclasses import replace

import pytest
from hub import agent_runtime as runtime
from hub.agent_instructions import instruction
from hub.agent_models import AgentJob, AgentStep
from hub.agent_native import prepare
from hub.db import Message, ProviderConfig, Run
from hub.provider_settings import seed
from hub.providers import Providers
from sqlalchemy import select
from test_actions import gateway, set_pause  # noqa: F401
from test_agent_capability_runtime import ha, start  # noqa: F401
from test_agents import agent  # noqa: F401
from test_integration_writes import writes  # noqa: F401


@pytest.fixture
def native_job(ha):  # noqa: F811
    app, _, _, cfg, identifier, *_ = ha
    cfg = replace(
        cfg,
        local_model="synthetic-native",
        local_allowed_ip="127.0.0.1",
        local_base_url="http://127.0.0.1:11444/v1",
    )
    job_id = start(ha, "Prüfe Home Assistant und installiere Updates", research_allowed=False)
    with app.state.sessions() as db:
        seed(db, cfg)
        row = db.get(ProviderConfig, "local-default")
        binding = {"id": row.id, "revision": row.revision, "model": cfg.local_model}
        job = db.get(AgentJob, job_id)
        profile, rules, _ = runtime.gate(db, cfg, job)[identifier]
        native = prepare(
            instruction({profile.kind}),
            {
                "goal": job.goal,
                "read_only": True,
                "allow_ask": False,
                "allow_finish": False,
                "allow_stop": False,
                "tools": ["http"],
                "interfaces": [
                    {
                        "integration_id": identifier,
                        "kind": profile.kind,
                        "read_only": True,
                        "rules": rules.model_dump(),
                    }
                ],
                "history": [],
            },
        )
        db.commit()
    return app.state.sessions, cfg, Providers(cfg), job_id, native, binding


def fake_execution(monkeypatch, modes, binding, *, hook=None):
    import hub.execution as execution

    outcomes = iter(modes)
    calls = []

    async def execute(factory, cfg, providers, run_id):
        with factory() as db:
            run = db.get(Run, run_id)
            snapshot = json.loads(run.context_snapshot)
            calls.append(snapshot)
            assert run.status == "queued"
            current = db.scalar(select(AgentStep).where(AgentStep.model_run_id == run.id))
            assert current.status == "dispatching"
            mode = next(outcomes)
            run.routing_trace = json.dumps({"native_provider": binding})
            if mode in {"unsupported", "auth", "timeout", "partial"}:
                run.status = "failed"
                run.error = {
                    "unsupported": "Native tool protocol unavailable",
                    "auth": "HTTP authentication failed",
                    "partial": "Stream incomplete",
                    "timeout": "Zeitlimit der Antworterzeugung erreicht.",
                }[mode]
            else:
                value = (
                    {"_native_error": "native_no_selection"}
                    if mode == "none"
                    else {"_native_error": "native_invalid_arguments",
                          "issues": ["schema_required:method", "schema_additionalProperties"]}
                    if mode == "invalid"
                    else {
                        "kind": "tool",
                        "integration_id": snapshot["agent_generation"]["integration_ids"][0],
                        "tool": "http",
                        "message": "Read states",
                        "arguments": {"method": "GET", "path": "/api/states"},
                    }
                )
                run.status = "succeeded"
                db.add(
                    Message(
                        conversation_id=run.conversation_id,
                        run_id=run.id,
                        role="assistant",
                        content=json.dumps(value),
                        label="LOCAL_ONLY",
                    )
                )
            db.commit()
        if hook:
            hook(factory, len(calls))

    monkeypatch.setattr(execution, "execute_run", execute)
    return calls


def generate(case):
    factory, cfg, providers, job_id, native, _ = case
    return asyncio.run(
        runtime.generate(
            factory, cfg, providers, job_id, native.instruction, {**native.data, "_native": native}
        )
    )


def records(case):
    factory, _, _, job_id, _, _ = case
    with factory() as db:
        return list(
            db.scalars(
                select(AgentStep).where(AgentStep.job_id == job_id).order_by(AgentStep.sequence)
            )
        )


def test_native_snapshot_uses_original_authority_and_keeps_aux_outside_message(
    native_job, monkeypatch
):
    calls = fake_execution(monkeypatch, ["success"], native_job[-1])
    assert generate(native_job)["arguments"]["path"] == "/api/states"
    snapshot = calls[0]
    generation = snapshot["agent_generation"]
    native = native_job[-2]
    assert generation["native_plan"] == native.metadata
    assert generation["interfaces"] == native.original_data["interfaces"]
    assert generation["read_only"] and not generation["allow_ask"]
    assert generation["tool_names"] == ["http"]
    assert generation["integration_ids"] == [
        native.original_data["interfaces"][0]["integration_id"]
    ]
    assert all(p["label"] == "LOCAL_ONLY" for p in snapshot["parts"])
    assert "_native" not in snapshot["parts"][1]["content"]
    steps = records(native_job)
    assert len(steps) == 1 and steps[0].status == "succeeded"
    assert json.loads(steps[0].document)["native_schema_sha256"] == native.metadata["sha256"]
    assert json.loads(steps[0].document)["protocol"] == "native"


@pytest.mark.parametrize("failure", ["none", "unsupported"])
def test_native_fallback_creates_separate_runs_and_pins_provider_once(
    native_job, monkeypatch, failure
):
    calls = fake_execution(monkeypatch, [failure, "success", "none"], native_job[-1])
    assert generate(native_job)["kind"] == "tool"
    assert len(calls) == 2
    first, second = [s["agent_generation"] for s in calls]
    assert "native_plan" in first and "native_plan" not in second
    assert second["provider_binding"] == native_job[-1]
    assert second["interfaces"] == first["interfaces"]
    factory, _, _, job_id, native, _ = native_job
    with factory() as db:
        bindings = json.loads(db.get(AgentJob, job_id).bindings)
        assert bindings["native_fallback_used"] and bindings["native_tools_disabled"]
        assert bindings["native_compatibility_provider"] == native_job[-1]
    steps = records(native_job)
    assert [s.status for s in steps] == ["failed", "succeeded"]
    assert len({s.model_run_id for s in steps}) == 2
    assert [json.loads(s.document)["protocol"] for s in steps] == ["native", "json"]
    assert (
        json.loads(calls[1]["parts"][1]["content"])["interfaces"]
        == native.original_data["interfaces"]
    )
    # Even a mistakenly repeated native request cannot create a second compatibility run.
    with pytest.raises(runtime.AgentPlanningError):
        generate(native_job)
    assert len(calls) == 3 and len(records(native_job)) == 3


@pytest.mark.parametrize("failure", ["invalid", "auth", "timeout", "partial"])
def test_invalid_or_transport_failure_never_uses_compatibility(native_job, monkeypatch, failure):
    calls = fake_execution(monkeypatch, [failure], native_job[-1])
    expected = runtime.AgentFormatError if failure == "invalid" else runtime.AgentPlanningError
    with pytest.raises(expected):
        generate(native_job)
    assert len(calls) == 1 and records(native_job)[0].status == "failed"
    factory, _, _, job_id, _, _ = native_job
    with factory() as db:
        assert not json.loads(db.get(AgentJob, job_id).bindings).get("native_fallback_used")


@pytest.mark.parametrize("budget", ["chars", "utf8"])
def test_auxiliary_schema_counts_before_any_run_is_created(native_job, monkeypatch, budget):
    native = native_job[-2]
    from hub.agent_native import auxiliary_parts

    message_chars = len(native.instruction) + len(runtime.encode(native.data))
    message_bytes = len(native.instruction.encode()) + len(runtime.encode(native.data).encode())
    auxiliary = auxiliary_parts(native.metadata)
    assert sum(len(p.content) for p in auxiliary) > 0
    char_limit, bytes_limit = (
        (message_chars + 1, None) if budget == "chars" else (1000000, message_bytes + 64 + 1)
    )
    monkeypatch.setattr(runtime, "generation_context_budget", lambda *a: (char_limit, bytes_limit))
    calls = fake_execution(monkeypatch, [], native_job[-1])
    with pytest.raises(runtime.AgentContextLimitError):
        generate(native_job)
    assert not calls and not records(native_job)


def test_provider_revision_change_blocks_compatibility_before_second_run(native_job, monkeypatch):
    def revoke(factory, count):
        assert count == 1
        with factory() as db:
            db.get(ProviderConfig, "local-default").revision += 1
            db.commit()

    calls = fake_execution(monkeypatch, ["unsupported"], native_job[-1], hook=revoke)
    with pytest.raises(PermissionError):
        generate(native_job)
    assert len(calls) == 1 and len(records(native_job)) == 1


def test_missing_provider_proof_does_not_enable_fallback(native_job, monkeypatch):
    calls = fake_execution(monkeypatch, ["none"], None)
    with pytest.raises(runtime.AgentPlanningError):
        generate(native_job)
    assert len(calls) == 1 and len(records(native_job)) == 1


@pytest.mark.parametrize("revocation", ["cancel", "target"])
def test_revocation_after_native_failure_blocks_compatibility(native_job, monkeypatch, revocation):
    from hub.agent_models import AgentPolicy

    def revoke(factory, count):
        assert count == 1
        with factory() as db:
            job = db.get(AgentJob, native_job[3])
            if revocation == "cancel":
                job.cancel_requested = True
            else:
                target = json.loads(job.bindings)["profiles"][0]["id"]
                db.get(AgentPolicy, target).revision += 1
            db.commit()

    calls = fake_execution(monkeypatch, ["none"], native_job[-1], hook=revoke)
    with pytest.raises(PermissionError):
        generate(native_job)
    assert len(calls) == 1 and len(records(native_job)) == 1
    with native_job[0]() as db:
        assert not json.loads(db.get(AgentJob, native_job[3]).bindings).get("native_fallback_used")


def test_native_safe_schema_diagnostics_reach_bounded_correction(native_job, monkeypatch):
    calls = fake_execution(monkeypatch, ["invalid"], native_job[-1])
    with pytest.raises(runtime.AgentFormatError) as caught:
        generate(native_job)
    issues = [{"type": "native_call_invalid", "diagnostics": [
        "schema_required:method", "schema_additionalProperties"]}]
    assert caught.value.issues == issues
    factory, cfg, _, job_id, *_ = native_job
    with factory() as db:
        job = db.get(AgentJob, job_id)
        runtime.format_feedback(db, cfg, job, caught.value.rejected, caught.value.issues)
        db.commit()
    assert len(calls) == 1
    feedback = records(native_job)[-1]
    assert feedback.kind == "feedback" and feedback.status == "succeeded"
    assert json.loads(feedback.document)["issues"] == issues
