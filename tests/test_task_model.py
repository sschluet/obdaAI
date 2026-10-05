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
