import asyncio
import json

import pytest
import test_chat
from hub.action_api import encode
from hub.db import TaskStep
from hub.task_model import execute_task
from test_tasks import control, create, queued, run_body, terminal


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


class AnalysisProvider(test_chat.FakeProviders):
    def __init__(self, fail=False):
        super().__init__()
        self.parts = []
        self.fail = fail

    async def stream(self, parts, roles, *, external, grants):
        assert external is False and grants == []
        self.parts = parts
        self.stream_calls.append(external)
        yield "SYNTHETIC_PARTIAL"
        await asyncio.sleep(0.05)
        if self.fail:
            raise ValueError("SENSITIVE_PROVIDER_ERROR")
        yield "_COMPLETE"


def task(c, h, **changes):
    return control(c, h, create(c, h, steps=[{"tool_id": "ai.analyze"}], **changes)).json()


def test_api_analysis_persists_prompt_model_and_no_duplicate_inference(setup):
    app, c, h, _ = setup
    provider = AnalysisProvider()
    app.state.providers = provider
    t = task(c, h)
    body = run_body(t)
    result = c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=body)
    assert result.status_code == 200
    receipt = terminal(c, t)
    assert receipt["status"] == "succeeded"
    step = receipt["steps"][0]["result"]
    assert step["answer"] == "SYNTHETIC_PARTIAL_COMPLETE" and not step["partial"]
    assert step["model"]["kind"] == "local" and step["cost_usd"] == 0
    assert step["input"][-1]["content"] == t["spec"]["goal"]
    assert provider.stream_calls == [False]
    assert (
        c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=body).json()["id"]
        == receipt["id"]
    )
    asyncio.run(execute_task(app.state.sessions, app.state.settings, receipt["id"], provider))
    assert provider.stream_calls == [False]


def test_partial_failure_preserved_without_secret_or_retry(setup):
    app, c, h, _ = setup
    provider = AnalysisProvider(fail=True)
    app.state.providers = provider
    t = task(c, h)
    c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t))
    receipt = terminal(c, t)
    assert receipt["status"] == "failed" and "SENSITIVE" not in receipt["error"]
    assert receipt["steps"][0]["result"]["answer"] == "SYNTHETIC_PARTIAL"
    assert receipt["steps"][0]["result"]["partial"]
    asyncio.run(execute_task(app.state.sessions, app.state.settings, receipt["id"], provider))
    assert provider.stream_calls == [False]


def test_restart_running_receipt_never_repeats_inference(setup):
    app, c, h, provider = setup
    t = task(c, h)
    rid = queued(app, t, status="running")
    with app.state.sessions() as db:
        db.add(
            TaskStep(
                run_id=rid,
                sequence=1,
                tool_id="ai.analyze",
                result=encode({"answer": "Persisted partial", "partial": True}),
            )
        )
        db.commit()
    asyncio.run(execute_task(app.state.sessions, app.state.settings, rid, provider))
    receipt = terminal(c, t)
    assert receipt["status"] == "failed" and "unterbrochen" in receipt["error"]
    assert receipt["steps"][0]["result"]["answer"] == "Persisted partial"
    assert provider.stream_calls == []


def test_cancel_running_keeps_active_guard_until_acknowledged(setup):
    app, c, h, _ = setup
    provider = AnalysisProvider()
    app.state.providers = provider
    t = task(c, h)
    rid = queued(app, t, status="running")
    response = c.post("/api/task-runs/" + rid + "/cancel", headers=h, json={})
    assert (
        response.json()["status"] == "running" and response.json()["error"] == "Abbruch angefordert"
    )
    assert c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t)).status_code == 409
    asyncio.run(execute_task(app.state.sessions, app.state.settings, rid, provider))
    assert terminal(c, t)["status"] == "cancelled" and provider.stream_calls == []


@pytest.mark.parametrize(
    "steps",
    [
        [{"tool_id": "ai.analyze"}, {"tool_id": "hub.inspect"}],
        [{"tool_id": "ai.analyze"}, {"tool_id": "ai.analyze"}],
        [{"tool_id": "ai.analyze", "parameters": {"provider": "openrouter"}}],
        [{"tool_id": "ai.analyze", "parameters": {"url": "https://evil.example"}}],
    ],
)
def test_model_step_cannot_choose_provider_targets_or_repeat(setup, steps):
    _, c, h, _ = setup
    assert (
        c.post(
            "/api/tasks", headers=h, json={"title": "Synthetic", "goal": "Read", "steps": steps}
        ).status_code
        == 422
    )


def test_concurrent_delivery_only_one_model_call(setup):
    app, c, h, _ = setup
    t = task(c, h)
    rid = queued(app, t)
    provider = AnalysisProvider()

    async def work():
        await asyncio.gather(
            *[execute_task(app.state.sessions, app.state.settings, rid, provider) for _ in range(3)]
        )

    asyncio.run(work())
    assert terminal(c, t)["status"] == "succeeded"
    assert provider.stream_calls == [False]


def test_bound_trusted_skill_applies_to_model_context(setup):
    app, c, h, _ = setup
    doc = (
        "---\n"
        + json.dumps({"format": "obdaai-skill-1", "name": "Synthetic task skill"})
        + "\n---\nAnswer in two words."
    )
    s = c.post("/api/skills", headers=h, json={"document": doc}).json()
    c.post(
        "/api/skills/" + s["id"] + "/trust",
        headers=h,
        json={"expected_revision": 1, "sha256": s["sha256"], "enabled": True},
    )
    t = task(c, h, skills=[{"id": s["id"], "revision": 1, "sha256": s["sha256"]}])
    provider = AnalysisProvider()
    app.state.providers = provider
    c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t))
    receipt = terminal(c, t)
    assert receipt["status"] == "succeeded"
    assert any("Answer in two words." in p.content for p in provider.parts)
    assert receipt["snapshot"]["skills_checked"][0]["sha256"] == s["sha256"]


def test_local_runtime_does_not_load_cloud_secrets(setup):
    from dataclasses import replace

    from hub.db import ProviderConfig
    from hub.provider_settings import runtime_provider, seed

    app, _, _, _ = setup
    cfg = replace(
        app.state.settings,
        local_base_url="http://127.0.0.1:1234/v1",
        local_allowed_ip="127.0.0.1",
        local_model="synthetic",
    )
    with app.state.sessions() as db:
        seed(db, cfg)
        db.get(
            ProviderConfig, "openrouter-default"
        ).encrypted_secret = "INVALID_CLOUD_SECRET_DO_NOT_LOAD"
        db.commit()
    local, provider, selected = runtime_provider(app.state.sessions, cfg, local_only=True)
    assert not local.cloud_enabled and not local.openrouter_key_file
    assert set(selected) == {"local"} and "openrouter" not in provider.keys


def test_only_explicit_source_chunks_enter_task_model_context(setup):
    from hub.db import Project, Source, SourceChunk

    app, c, h, _ = setup
    with app.state.sessions() as db:
        p = Project(name="Synthetic scope")
        db.add(p)
        db.flush()
        one = Source(project_id=p.id, name="Allowed", sha256="a" * 64, size=1, status="ready")
        two = Source(project_id=p.id, name="Unbound", sha256="b" * 64, size=1, status="ready")
        db.add_all([one, two])
        db.flush()
        db.add_all(
            [
                SourceChunk(source_id=one.id, locator="paragraph 1", content="ALLOWED_SYNTHETIC"),
                SourceChunk(
                    source_id=two.id, locator="paragraph 1", content="UNBOUND_PRIVATE_SYNTHETIC"
                ),
            ]
        )
        db.commit()
        pid, sid = p.id, one.id
    t = task(c, h, project_id=pid, sources=[{"id": sid, "revision": 1, "sha256": "a" * 64}])
    provider = AnalysisProvider()
    app.state.providers = provider
    c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t))
    assert terminal(c, t)["status"] == "succeeded"
    text = "\n".join(p.content for p in provider.parts)
    assert "ALLOWED_SYNTHETIC" in text and "UNBOUND_PRIVATE_SYNTHETIC" not in text


def test_local_analysis_consumes_real_prior_read_evidence_once(setup):
    app, c, h, _ = setup
    provider = AnalysisProvider()
    app.state.providers = provider
    t = control(
        c,
        h,
        create(
            c,
            h,
            goal="Read the workspace, then analyze that result.",
            steps=[{"tool_id": "hub.inspect"}, {"tool_id": "ai.analyze"}],
        ),
    ).json()
    c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t))
    receipt = terminal(c, t)
    assert receipt["status"] == "succeeded" and len(receipt["steps"]) == 2
    prior = receipt["steps"][0]["result"]
    analysis = receipt["steps"][1]["result"]
    evidence = [p for p in analysis["input"] if p["source_id"].startswith("task-step:")]
    assert len(evidence) == 1 and evidence[0]["label"] == "LOCAL_ONLY"
    assert json.loads(evidence[0]["content"].split("\n", 1)[1]) == prior
    assert analysis["input"][-1]["content"] == t["spec"]["goal"]
    asyncio.run(execute_task(app.state.sessions, app.state.settings, receipt["id"], provider))
    assert provider.stream_calls == [False]


def test_explicit_system_report_pipeline_preserves_order_and_local_audit(setup, monkeypatch):
    app, c, h, _ = setup
    calls = []

    def report(cfg):
        calls.append("ha")
        return {"version": "SYNTHETIC_HA_REPORT", "updates": 0, "label": "LOCAL_ONLY"}

    monkeypatch.setattr("hub.home_assistant.inspect", report)
    provider = AnalysisProvider()
    app.state.providers = provider
    t = control(
        c,
        h,
        create(
            c,
            h,
            include_system_reports=True,
            steps=[
                {"tool_id": "ha.inspect"},
                {"tool_id": "hub.inspect"},
                {"tool_id": "ai.analyze"},
            ],
            timeout_seconds=30,
        ),
    ).json()
    c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t)).raise_for_status()
    receipt = terminal(c, t)
    assert receipt["status"] == "succeeded", receipt
    assert [s["tool_id"] for s in receipt["steps"]] == ["ha.inspect", "hub.inspect", "ai.analyze"]
    audit = receipt["steps"][-1]["result"]
    assert any("SYNTHETIC_HA_REPORT" in p["content"] for p in audit["input"])
    assert all(p["label"] == "LOCAL_ONLY" for p in audit["input"]) and audit["cost_usd"] == 0
    asyncio.run(execute_task(app.state.sessions, app.state.settings, receipt["id"], provider))
    assert calls == ["ha"] and provider.stream_calls == [False]


def test_system_report_is_never_implicitly_given_to_model(setup):
    app, c, h, _ = setup
    result = c.post(
        "/api/tasks",
        headers=h,
        json={
            "title": "No consent",
            "goal": "Read",
            "steps": [{"tool_id": "ha.inspect"}, {"tool_id": "ai.analyze"}],
        },
    )
    assert result.status_code == 422
    from hub.task_api import TaskSpec

    old = TaskSpec(title="Old scope", goal="Read")
    assert "include_system_reports" not in old.model_dump(mode="json")


def test_report_cancellation_stops_before_local_model(setup, monkeypatch):
    app, c, h, _ = setup
    provider = AnalysisProvider()
    app.state.providers = provider
    t = control(
        c,
        h,
        create(
            c,
            h,
            include_system_reports=True,
            steps=[{"tool_id": "ha.inspect"}, {"tool_id": "ai.analyze"}],
            timeout_seconds=30,
        ),
    ).json()

    def report(cfg):
        with app.state.sessions() as db:
            from hub.db import Task

            task = db.get(Task, t["id"])
            task.paused = True
            task.control_revision += 1
            db.commit()
        return {"label": "LOCAL_ONLY", "version": "SYNTHETIC_CANCELLED_REPORT"}

    monkeypatch.setattr("hub.home_assistant.inspect", report)
    c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t)).raise_for_status()
    result = terminal(c, t)
    assert result["status"] == "failed" and provider.stream_calls == []
    assert result["steps"][-1]["result"]["partial"]


@pytest.mark.parametrize(
    "available,unknown,expected_calls,expected_status",
    [(0, 0, 0, "succeeded"), (2, 0, 1, "succeeded"), (0, 1, 0, "failed")],
)
def test_update_condition_is_local_bounded_and_does_not_guess_unknown_state(
    setup, monkeypatch, available, unknown, expected_calls, expected_status
):
    app, c, h, _ = setup
    monkeypatch.setattr(
        "hub.home_assistant.inspect",
        lambda cfg: {
            "label": "LOCAL_ONLY",
            "available_updates": available,
            "unavailable_updates": unknown,
        },
    )
    provider = AnalysisProvider()
    app.state.providers = provider
    t = control(
        c,
        h,
        create(
            c,
            h,
            include_system_reports=True,
            analysis_condition="ha_updates_available",
            steps=[{"tool_id": "ha.inspect"}, {"tool_id": "ai.analyze"}],
            timeout_seconds=30,
        ),
    ).json()
    c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t)).raise_for_status()
    result = terminal(c, t)
    assert result["status"] == expected_status
    assert len(provider.stream_calls) == expected_calls
    if expected_status == "succeeded" and not expected_calls:
        assert result["steps"][-1]["result"]["skipped"] is True
        assert result["steps"][-1]["result"]["partial"] is False


def bind_paperless(app, task_id):
    from hub.integrations import Integration, IntegrationBinding

    with app.state.sessions() as db:
        profile = Integration(
            name="Synthetic archive",
            kind="paperless",
            enabled=True,
            config=encode({"url": "https://archive.example.test", "auth": "api_key"}),
        )
        db.add(profile)
        db.flush()
        db.add(
            IntegrationBinding(
                scope="task",
                owner_id=task_id,
                integration_ids=encode([profile.id]),
                selection_mode="manual",
            )
        )
        identifier = profile.id
        db.commit()
    return identifier


def test_task_selected_paperless_frozen_and_consumed_locally(setup, monkeypatch):
    from hub.policy import ContextPart

    app, c, h, _ = setup
    provider = AnalysisProvider()
    app.state.providers = provider
    t = task(c, h)
    identifier = bind_paperless(app, t["id"])

    async def collect(factory, cfg, selection, question):
        assert selection["bindings"][0]["id"] == identifier
        assert question == t["spec"]["goal"]
        return [
            ContextPart(
                content="Synthetic private archive evidence",
                source_id="paperless:" + identifier + ":7",
                revision=1,
            )
        ]

    monkeypatch.setattr("hub.task_model.collect_context", collect)
    response = c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t))
    assert response.status_code == 200
    receipt = terminal(c, t)
    assert receipt["status"] == "succeeded"
    assert receipt["steps"][0]["tool_id"] == "paperless.context"
    assert receipt["steps"][0]["result"]["state"] == "read"
    assert any("Synthetic private archive" in p.content for p in provider.parts)
    assert receipt["steps"][1]["result"]["input"][-1]["content"] == t["spec"]["goal"]
    assert provider.stream_calls == [False]


def test_task_paperless_disable_during_context_prevents_model(setup, monkeypatch):
    from hub.integrations import Integration
    from hub.policy import ContextPart

    app, c, h, _ = setup
    provider = AnalysisProvider()
    app.state.providers = provider
    t = task(c, h)
    identifier = bind_paperless(app, t["id"])

    async def collect(factory, cfg, selection, question):
        with factory() as db:
            db.get(Integration, identifier).enabled = False
            db.commit()
        return [
            ContextPart(
                content="Private evidence", source_id="paperless:" + identifier + ":7", revision=1
            )
        ]

    monkeypatch.setattr("hub.task_model.collect_context", collect)
    c.post("/api/tasks/" + t["id"] + "/runs", headers=h, json=run_body(t))
    assert terminal(c, t)["status"] == "failed"
    assert provider.stream_calls == []


def test_task_project_inheritance_only_when_no_task_binding(setup):
    from hub.db import Project
    from hub.integrations import Integration, IntegrationBinding
    from hub.task_api import TaskSpec, task_integrations

    app, _, _, _ = setup
    with app.state.sessions() as db:
        project = Project(name="Synthetic inherited archive")
        profile = Integration(name="Archive", kind="paperless", enabled=True, config="{}")
        db.add_all([project, profile])
        db.flush()
        db.add(
            IntegrationBinding(
                scope="project", owner_id=project.id, integration_ids=encode([profile.id])
            )
        )
        db.flush()
        spec = TaskSpec(
            title="Synthetic",
            goal="Synthetic",
            project_id=project.id,
            steps=[{"tool_id": "ai.analyze"}],
        )
        assert task_integrations(db, "task-synthetic", spec)["bindings"][0]["id"] == profile.id
        db.add(IntegrationBinding(scope="task", owner_id="task-synthetic", selection_mode="off"))
        db.flush()
        assert task_integrations(db, "task-synthetic", spec)["bindings"] == []


def test_clock_and_source_event_enqueue_freeze_paperless(setup):
    import time

    import test_schedules
    import test_source_events

    app, c, h, _ = setup
    now = time.time()
    scheduled = test_schedules.armed(app, c, h, now - 10)
    identifier = bind_paperless(app, scheduled["id"])
    job = test_schedules.pulse(app, now)[0]
    with app.state.sessions() as db:
        frozen = json.loads(db.get(TaskStep, (job, 0)).result)
        assert frozen["selection"]["bindings"][0]["id"] == identifier
    pid = test_source_events.project(c, h)
    event_task = test_source_events.armed(app, c, h, pid)
    identifier = bind_paperless(app, event_task["id"])
    test_source_events.ready(app, pid, now)
    job = test_schedules.pulse(app, now + 1)[0]
    with app.state.sessions() as db:
        frozen = json.loads(db.get(TaskStep, (job, 0)).result)
        assert frozen["selection"]["bindings"][0]["id"] == identifier
