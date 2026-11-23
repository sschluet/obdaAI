"""Project preferences select real transport adapters; they do not grant cloud access."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from hub.db import Conversation, Project, ProviderConfig, Run, TaskRevision, TaskRun
from hub.inference_capacity import local_capacity
from hub.project_models import CLOUD_BLOCKED, ProjectModelError, check, freeze
from hub.providers import Providers
from hub.task_drafts import preview
from hub.task_model import execute_task
from sqlalchemy import select
from test_provider_settings import payload
from test_task_model import task
from test_tasks import queued, run_body, terminal

pytest_plugins = ["test_provider_settings"]


def configured(managed, model="chosen-project-model", kind="local"):
    app, client, headers, cfg = managed
    value = {**payload(kind), "model": model, "name": "Synthetic configured model"}
    response = client.post("/api/providers", headers=headers, json=value)
    assert response.status_code == 200, response.text
    return response.json()


def project(managed, provider=None):
    _, client, headers, _ = managed
    response = client.post("/api/projects", headers=headers, json={
        "name": "Synthetic project", "instructions": "Synthetic project instructions",
        "model_policy": {"provider_id": provider["id"], "model": provider["model"]}
        if provider else {},
    })
    assert response.status_code == 200, response.text
    return response.json()


def save(managed, row, policy):
    _, client, headers, _ = managed
    result = client.patch("/api/projects/" + row["id"], headers=headers, json={
        "name": row["name"], "description": row["description"], "instructions": row["instructions"],
        "revision": row["revision"], "model_policy": policy,
    })
    assert result.status_code == 200, result.text
    return result.json()


def transport(monkeypatch):
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            text = "SYNTHETIC PROJECT ANSWER"
            if "Synthetic planner instruction" in body["messages"][0]["content"]:
                text = json.dumps({"kind": "finish", "message": "Synthetic planner answer"})
            if "Create a title and a fixed read-only task kind" in body["messages"][0]["content"]:
                text = json.dumps({"title": "Synthetic draft", "kind": "analysis"})
            return httpx.Response(200, text="data: " + json.dumps({"choices": [{
                "delta": {"content": text}, "finish_reason": "stop"}]}) + "\n\ndata: [DONE]\n\n")
        if "exactly one key: title" in body["messages"][0]["content"]:
            content = {"title": "Synthetic title"}
        else:
            # A model's cloud preference cannot override a fixed local project choice.
            content = {"capabilities": ["chat"], "model_class": "cloud", "reason": "Synthetic",
                       "answer": None}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
        )

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)))
    return requests


def test_project_policy_cas_omission_auto_and_no_provider_default_changes(managed):
    app, client, headers, _ = managed
    provider = configured(managed)
    with app.state.sessions() as db:
        defaults = {r.id: r.is_default for r in db.scalars(select(ProviderConfig))}
    p = project(managed, provider)
    assert p["model_policy_status"]["available"]
    assert p["model_policy"] == {"provider_id": provider["id"], "model": provider["model"]}
    changed = client.patch("/api/projects/" + p["id"], headers=headers, json={
        "name": "Synthetic renamed", "revision": p["revision"]})
    assert changed.status_code == 200 and changed.json()["model_policy"] == p["model_policy"]
    assert client.patch("/api/projects/" + p["id"], headers=headers, json={
        "name": "stale", "revision": p["revision"], "model_policy": {}}).status_code == 409
    reset = save(managed, changed.json(), {})
    assert reset["model_policy"] == {} and reset["model_policy_status"]["available"]
    with app.state.sessions() as db:
        assert {r.id: r.is_default for r in db.scalars(select(ProviderConfig))} == defaults


def test_project_chat_uses_nondefault_selected_model_for_actual_answer(managed, monkeypatch):
    app, client, headers, _ = managed
    provider = configured(managed)
    p = project(managed, provider)
    requests = transport(monkeypatch)
    response = client.post("/api/conversations", headers=headers, json={"project_id": p["id"]})
    chat = response.json()["id"]
    result = client.post("/api/conversations/" + chat + "/messages", headers=headers,
                         json={"content": "Synthetic question"})
    assert result.status_code == 200 and "SYNTHETIC PROJECT ANSWER" in result.text
    assert [r["model"] for r in requests if r.get("stream")] == [provider["model"]]
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == chat))
        assert run.status == "succeeded" and run.model == provider["model"]
        assert json.loads(run.context_snapshot)["project_model"]["provider_id"] == provider["id"]
        assert db.get(Project, p["id"]).label == "LOCAL_ONLY"
        assert not db.get(Conversation, chat).cloud_allowed


def test_saved_task_inherits_changed_model_without_reapproval(managed, monkeypatch):
    app, client, headers, _ = managed
    first, second = configured(managed, "project-model-A"), configured(managed, "project-model-B")
    p = project(managed, first)
    t = task(client, headers, project_id=p["id"])
    with app.state.sessions() as db:
        original_spec = db.get(TaskRevision, (t["id"], t["revision"])).spec
    requests = transport(monkeypatch)
    for chosen in [first, second]:
        if chosen is second:
            p = save(managed, p, {"provider_id": second["id"], "model": second["model"]})
        result = client.post("/api/tasks/" + t["id"] + "/runs", headers=headers, json=run_body(t))
        assert result.status_code == 200, result.text
        receipt = terminal(client, t)
        assert receipt["status"] == "succeeded", receipt
        assert receipt["steps"][0]["result"]["model"]["model"] == chosen["model"]
    assert [r["model"] for r in requests if r.get("stream")] == [first["model"], second["model"]]
    with app.state.sessions() as db:
        assert db.get(TaskRevision, (t["id"], t["revision"])).spec == original_spec


def test_project_task_draft_uses_selected_model_and_keeps_project(managed, monkeypatch):
    app, client, headers, _ = managed
    chosen = configured(managed)
    p = project(managed, chosen)
    requests = transport(monkeypatch)
    result = client.post("/api/task-drafts", headers=headers,
                         json={"goal": "Synthetic task", "project_id": p["id"]})
    assert result.status_code == 200, result.text
    assert result.json()["spec"]["project_id"] == p["id"]
    assert not result.json()["saved"] and not result.json()["started"]
    assert [r["model"] for r in requests] == [chosen["model"]]


def test_fixed_cloud_is_saved_but_project_chat_and_model_task_are_blocked(managed, monkeypatch):
    app, client, headers, cfg = managed
    cloud = configured(managed, "synthetic-cloud-model", "openrouter")
    p = project(managed, cloud)
    assert not p["model_policy_status"]["available"]
    assert p["model_policy_status"]["reason"] == CLOUD_BLOCKED
    requests = transport(monkeypatch)
    chat = client.post("/api/conversations", headers=headers,
                       json={"project_id": p["id"]}).json()["id"]
    result = client.post("/api/conversations/" + chat + "/messages", headers=headers,
                         json={"content": "Synthetic private question"})
    assert result.status_code == 409 and CLOUD_BLOCKED in result.json()["detail"]
    # Direct execution also rejects it; no adapter invocation can bypass the API status.
    with pytest.raises(ProjectModelError, match="Cloud gewählt"):
        asyncio.run(preview(app.state.sessions, cfg, "Synthetic draft", project_id=p["id"]))
    t = task(client, headers, project_id=p["id"])
    result = client.post("/api/tasks/" + t["id"] + "/runs", headers=headers, json=run_body(t))
    assert result.status_code == 200
    receipt = terminal(client, t)
    assert receipt["status"] == "failed" and receipt["error"] == CLOUD_BLOCKED
    assert requests == []


@pytest.mark.parametrize("change", ["project", "provider", "disabled", "model", "archived"])
def test_project_provider_freeze_rejects_authority_changes(managed, change):
    app, _, _, cfg = managed
    chosen = configured(managed)
    p = project(managed, chosen)
    with app.state.sessions() as db:
        frozen = freeze(db, cfg, p["id"])
        project_row = db.get(Project, p["id"])
        row = db.get(ProviderConfig, chosen["id"])
        if change == "project":
            project_row.revision += 1
        elif change == "provider":
            row.revision += 1
        elif change == "disabled":
            row.enabled = False
        elif change == "archived":
            project_row.archived = True
        elif change == "model":
            row.config = json.dumps({**json.loads(row.config), "model": "different"})
        db.commit()
    with app.state.sessions() as db, pytest.raises(ProjectModelError):
        check(db, cfg, frozen)


@pytest.mark.parametrize("change", ["project", "provider_disabled", "provider_revision"])
def test_project_model_revocation_after_queue(managed, monkeypatch, tmp_path, change):
    app, client, headers, cfg = managed
    chosen = configured(managed)
    p = project(managed, chosen)
    t = task(client, headers, project_id=p["id"])
    rid = queued(app, t)
    from hub.action_api import encode
    from hub.task_api import TaskSpec, check_bindings

    with app.state.sessions() as db:
        db.get(TaskRun, rid).snapshot = encode(
            check_bindings(db, TaskSpec.model_validate(t["spec"]))
        )
        db.commit()
    requests = transport(monkeypatch)
    cfg = replace(cfg, source_dir=str(tmp_path))
    from hub import task_model
    original_runtime = task_model.runtime_provider
    waiting = None

    def selected_provider(*args, **kwargs):
        settings, provider, rows = original_runtime(*args, **kwargs)
        provider.on_progress = lambda phase: waiting.set() if phase == "waiting_for_model" else None
        return settings, provider, rows

    monkeypatch.setattr(task_model, "runtime_provider", selected_provider)

    async def scenario():
        nonlocal waiting
        waiting = asyncio.Event()
        async with local_capacity(cfg):
            work = asyncio.create_task(execute_task(app.state.sessions, cfg, rid, Providers(cfg)))
            await asyncio.wait_for(waiting.wait(), 2)
            with app.state.sessions() as db:
                if change == "project":
                    db.get(Project, p["id"]).revision += 1
                elif change == "provider_disabled":
                    db.get(ProviderConfig, chosen["id"]).enabled = False
                else:
                    db.get(ProviderConfig, chosen["id"]).revision += 1
                db.commit()
        await work
    asyncio.run(scenario())
    assert requests == [] and terminal(client, t)["status"] == "failed"


def test_project_use_case_answer_uses_fixed_model(managed, monkeypatch):
    from test_use_case_ai import ai_spec, run, wait

    app, client, headers, _ = managed
    chosen = configured(managed)
    p = project(managed, chosen)
    result = client.post("/api/projects/" + p["id"] + "/use-cases", headers=headers,
                         json={"spec": ai_spec()})
    assert result.status_code == 200, result.text
    case = result.json()
    requests = transport(monkeypatch)
    started = run(client, headers, case)
    done = wait(client, f"/api/use-cases/{case['id']}/runs/{started['id']}")
    assert done["status"] == "succeeded", done
    assert [request["model"] for request in requests] == [chosen["model"]]
    with app.state.sessions() as db:
        actual = db.get(Run, started["execution_run_id"])
        assert actual.model == chosen["model"]
        assert json.loads(actual.context_snapshot)["project_model"]["project_id"] == p["id"]


def test_hidden_agent_planning_run_carries_owning_project_model(managed, monkeypatch):
    from uuid import uuid4

    from hub import agent_runtime
    from hub.agent_intent import RequestIntent, Requirement
    from hub.agent_models import AgentPolicy
    from hub.agent_tools import Rules
    from hub.db import ActionPolicy
    from hub.integrations import Integration, IntegrationBinding
    from hub.knowledge import context as project_context

    app, _, _, cfg = managed
    chosen = configured(managed)
    p = project(managed, chosen)
    cfg = replace(cfg, integration_targets_enabled=True)
    with app.state.sessions() as db:
        if not db.get(ActionPolicy, 1):
            db.add(ActionPolicy(id=1, paused=True))
        chat = Conversation(project_id=p["id"], title="Synthetic agent parent")
        target = Integration(kind="home_assistant", name="Synthetic HA", enabled=True,
                             config=json.dumps({"kind": "home_assistant", "auth": "none",
                                                "url": "https://synthetic.example.invalid"}))
        db.add_all([chat, target])
        db.flush()
        db.add_all([
            IntegrationBinding(scope="conversation", owner_id=chat.id,
                               integration_ids=json.dumps([target.id])),
            AgentPolicy(integration_id=target.id, profile_revision=target.revision,
                        rules=Rules(enabled=True, http_prefixes=["/api/"], http_methods=["GET"],
                                    max_effects=0).model_dump_json()),
        ])
        db.flush()
        intent = RequestIntent(target_ids=[target.id], mode="observe", topic="system",
                               requirements=[Requirement(kind="system", integration_id=target.id)])
        job = agent_runtime.create_job(db, cfg, scope="conversation", owner_id=chat.id,
            conversation_id=chat.id, goal="Inspect synthetic system", request_id=str(uuid4()),
            research_allowed=False, read_only=True, resolved_intent=intent.model_dump(mode="json"),
            context=[part.model_dump(mode="json")
                     for part in project_context(db, p["id"], "Inspect synthetic system")])
        db.commit()
        job_id = job.id
        assert json.loads(job.bindings)["project_model"]["provider_id"] == chosen["id"]
    requests = transport(monkeypatch)
    result = asyncio.run(agent_runtime.generate(app.state.sessions, cfg, Providers(cfg), job_id,
        "Synthetic planner instruction", {"intent_schema": {"type": "object"}}))
    assert result["kind"] == "finish"
    assert [request["model"] for request in requests] == [chosen["model"]]


def test_fresh_concurrent_settings_and_provider_catalog_seed_once(managed):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from hub.db import ProviderRevision
    from sqlalchemy import delete, func

    app, client, _, _ = managed
    with app.state.sessions() as db:
        db.execute(delete(ProviderRevision))
        db.execute(delete(ProviderConfig))
        db.commit()
    ready = Barrier(4)

    def request(path):
        ready.wait()
        return client.get(path).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(request, ["/api/settings", "/api/providers"] * 2))
    assert results == [200] * 4
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ProviderConfig)) == 2
        assert db.scalar(select(func.count()).select_from(ProviderRevision)) == 2


@pytest.mark.parametrize("is_default", [True, False])
def test_seed_preserves_existing_kind_even_without_reserved_default_id(managed, is_default):
    from hub.db import ProviderRevision
    from hub.provider_settings import seed
    from sqlalchemy import delete

    app, _, _, cfg = managed
    with app.state.sessions() as db:
        db.execute(delete(ProviderRevision))
        db.execute(delete(ProviderConfig))
        row = ProviderConfig(
            id="synthetic-owned-provider", name="Synthetic preserved", kind="local",
            revision=7, enabled=False, is_default=is_default, config='{"model":"synthetic"}',
            encrypted_secret="SYNTHETIC-OPAQUE-CIPHERTEXT")
        db.add(row)
        db.commit()
    with app.state.sessions() as db:
        seed(db, cfg)
        db.commit()
    with app.state.sessions() as db:
        row = db.get(ProviderConfig, "synthetic-owned-provider")
        assert row.revision == 7 and row.is_default == is_default and not row.enabled
        assert row.encrypted_secret == "SYNTHETIC-OPAQUE-CIPHERTEXT"
        assert db.get(ProviderConfig, "local-default") is None
        assert db.get(ProviderRevision, (row.id, 1)) is None
