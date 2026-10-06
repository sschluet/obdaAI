import base64
import copy
import json
import os
import uuid

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import TaskRun, WorkflowBinding, WorkflowDispatch
from hub.n8n_check import CheckError
from hub.n8n_workflows import task_workflow, verify_workflow
from sqlalchemy import func, select
from test_tasks import control, create, run_body, terminal


@pytest.fixture
def workflows(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "wf.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    key = tmp_path / "master.key"
    key.write_text(base64.b64encode(os.urandom(32)).decode())
    key.chmod(0o600)
    cfg = Settings(
        database_url=url,
        origin="http://testserver",
        secure_cookie=False,
        password_hash=password_hash("synthetic-password"),
        secrets_key_file=str(key),
        n8n_api_key_file="synthetic-only",
        n8n_allowed_ip="192.0.2.1",
        n8n_ca_credential_id="ca-fixed",
    )
    app = create_app(cfg)
    with TestClient(app) as c:
        login = c.post(
            "/api/login", headers={"Origin": cfg.origin}, json={"password": "synthetic-password"}
        ).json()
        h = {"Origin": cfg.origin, "X-CSRF-Token": login["csrf"]}
        yield app, c, h, monkeypatch


def review(t):
    return {k: v for k, v in run_body(t).items() if k != "request_id"}


def ready(fixture, **task_changes):
    app, c, h, monkeypatch = fixture
    t = create(c, h, goal="PRIVATE_TASK_CONTEXT_MUST_STAY_LOCAL", **task_changes)
    t = control(c, h, t).json()
    b = c.post("/api/tasks/" + t["id"] + "/workflows", headers=h, json=review(t)).json()
    provision = c.post(
        "/api/workflows/" + b["id"] + "/provisioning", headers=h, json=review(t)
    ).json()
    token = provision["credential"]["data"]["value"]
    graph = task_workflow(
        b["id"],
        t["id"],
        t["revision"],
        "header-fixed",
        "ca-fixed",
        wait_for_completion=t["spec"].get("workflow_wait", False),
    )
    version = str(uuid.uuid4())
    remote_state = {
        **copy.deepcopy(graph),
        "id": "wf-fixed",
        "versionId": version,
        "active": False,
        "activeVersionId": None,
    }
    calls = []

    def remote(cfg, path, *, token=None, payload=None):
        calls.append((path, payload))
        if path.startswith("/api/"):
            return copy.deepcopy(remote_state)
        assert path == "/webhook/obdaai-" + b["id"]
        assert set(payload) == {"dispatch_id"}
        r = c.post(
            "/api/workflow-callback/" + b["id"],
            headers={"X-OBDAAI-WORKFLOW": token},
            json={**payload, "execution_id": "42"},
        )
        r.raise_for_status()
        return r.json()

    monkeypatch.setattr("hub.workflow_api.remote", remote)
    reg = c.post(
        "/api/workflows/" + b["id"] + "/register",
        headers=h,
        json={
            **review(t),
            "workflow_id": "wf-fixed",
            "workflow_version": version,
            "header_credential_id": "header-fixed",
            "ca_credential_id": "ca-fixed",
        },
    )
    assert reg.status_code == 200, reg.text
    remote_state.update(active=True, activeVersionId=version)
    r = c.post("/api/workflows/" + b["id"] + "/confirm-active", headers=h, json=review(t))
    assert r.status_code == 200, r.text
    return t, b, token, calls, remote_state


def test_bound_real_template_and_durable_callback(workflows):
    app, c, h, _ = workflows
    t, b, token, calls, _ = ready(workflows)
    body = run_body(t)
    r = c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=body)
    assert r.status_code == 200, r.text
    d = r.json()["dispatches"][0]
    assert d["status"] == "accepted" and d["execution_id"] == "42"
    run = terminal(c, t)
    assert run["id"] == d["run_id"] and run["status"] == "succeeded"
    assert c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=body).json() == r.json()
    cb = {"dispatch_id": d["id"], "execution_id": "42"}
    assert (
        c.post(
            "/api/workflow-callback/" + b["id"], headers={"X-OBDAAI-WORKFLOW": token}, json=cb
        ).status_code
        == 200
    )
    assert len([p for p, data in calls if data is not None]) == 1
    assert "PRIVATE_TASK_CONTEXT" not in json.dumps(calls)
    assert token not in r.text
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(TaskRun)) == 1
        assert token not in db.get(WorkflowBinding, b["id"]).encrypted_secret


def test_unknown_outcome_never_reposts_and_late_callback_reconciles(workflows):
    app, c, h, mp = workflows
    t, b, token, calls, state = ready(workflows)

    def lost(cfg, path, **kwargs):
        calls.append((path, kwargs.get("payload")))
        if path.startswith("/api/"):
            return copy.deepcopy(state)
        raise httpx.ReadTimeout("synthetic lost response")

    mp.setattr("hub.workflow_api.remote", lost)
    body = run_body(t)
    r = c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=body)
    assert r.json()["dispatches"][0]["status"] == "uncertain"
    assert c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=body).status_code == 200
    assert (
        c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=run_body(t)).status_code
        == 409
    )
    assert len([p for p, v in calls if v is not None]) == 1
    cb = c.post(
        "/api/workflow-callback/" + b["id"],
        headers={"X-OBDAAI-WORKFLOW": token},
        json={"dispatch_id": body["request_id"], "execution_id": "99"},
    )
    assert cb.status_code == 200
    assert terminal(c, t)["status"] == "succeeded"
    with app.state.sessions() as db:
        assert db.get(WorkflowDispatch, body["request_id"]).status == "accepted"


@pytest.mark.parametrize("mutation", ["graph", "version", "active_version", "inactive"])
def test_remote_drift_blocks_before_post(workflows, mutation):
    app, c, h, _ = workflows
    t, b, token, calls, state = ready(workflows)
    if mutation == "graph":
        state["nodes"][1]["parameters"]["url"] = "https://unreviewed.invalid"
    elif mutation == "version":
        state["versionId"] = str(uuid.uuid4())
    elif mutation == "active_version":
        state["activeVersionId"] = str(uuid.uuid4())
    else:
        state["active"] = False
    r = c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=run_body(t))
    assert r.status_code == 409
    assert not any(payload for path, payload in calls)
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(WorkflowDispatch)) == 0


def test_callback_auth_and_revision_and_parameters(workflows):
    app, c, h, mp = workflows
    t, b, token, calls, state = ready(workflows)
    body = run_body(t)
    mp.setattr("hub.workflow_api.remote", lambda cfg, path, **kw: state)
    c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=body)
    cb = {"dispatch_id": body["request_id"], "execution_id": "1"}
    assert c.post("/api/workflow-callback/" + b["id"], json=cb).status_code == 401
    assert (
        c.post(
            "/api/workflow-callback/" + b["id"],
            headers={"X-OBDAAI-WORKFLOW": token},
            json={**cb, "url": "bad"},
        ).status_code
        == 422
    )
    assert control(c, h, t, paused=True).status_code == 200
    assert (
        c.post(
            "/api/workflow-callback/" + b["id"], headers={"X-OBDAAI-WORKFLOW": token}, json=cb
        ).status_code
        == 409
    )
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(TaskRun)) == 0


def test_preparation_is_local_and_idempotent(workflows):
    app, c, h, mp = workflows
    mp.setattr("hub.workflow_api.remote", lambda *a, **k: pytest.fail("Draft did remote I/O"))
    t = create(c, h)
    path = "/api/tasks/" + t["id"] + "/workflows"
    first = c.post(path, headers=h, json=review(t))
    assert first.status_code == 200 and first.json()["status"] == "draft"
    assert c.post(path, headers=h, json=review(t)).json() == first.json()
    assert c.post(path, json=review(t)).status_code == 403
    assert c.get(path).json()["bindings"] == [first.json()]


def test_template_rejects_unapproved_changes():
    graph = task_workflow(str(uuid.uuid4()), str(uuid.uuid4()), 1, "fixed", "ca")
    remote = {**graph, "id": "wf", "versionId": str(uuid.uuid4()), "active": False}
    assert verify_workflow(remote, graph, active=False) == "wf"
    bad = copy.deepcopy(remote)
    bad["nodes"][1]["parameters"]["jsonBody"] = "={{ $json.body }}"
    with pytest.raises(CheckError):
        verify_workflow(bad, graph, active=False)


def action(c, h, t, b, tool, version=None):
    policy = c.get("/api/action-policy").json()
    if policy["paused"]:
        assert (
            c.patch(
                "/api/action-policy",
                headers=h,
                json={"paused": False, "expected_revision": policy["revision"]},
            ).status_code
            == 200
        )
    a = c.post(
        "/api/actions",
        headers=h,
        json={
            "request_id": str(uuid.uuid4()),
            "tool_id": tool,
            "parameters": {"binding_id": b["id"], **review(t), "workflow_version": version},
        },
    ).json()
    r = c.post(
        "/api/actions/" + a["id"] + "/grant",
        headers=h,
        json={"parameters_sha256": a["parameters_sha256"], "tool_revision": 1, "ttl_seconds": 300},
    )
    assert r.status_code == 200, r.text
    return r.json()


def operator_setup(workflows, *, lose_credential=False, lose_workflow=False, lose_activation=False):
    app, c, h, mp = workflows
    t = create(c, h)
    b = c.post("/api/tasks/" + t["id"] + "/workflows", headers=h, json=review(t)).json()
    a = action(c, h, t, b, "n8n.workflow.provision")
    calls, state = [], {}

    def remote(cfg, path, *, token=None, payload=None):
        calls.append((path, payload is not None))
        if path == "/api/v1/credentials":
            assert payload["type"] == "httpHeaderAuth"
            assert payload["data"]["name"] == "X-OBDAAI-WORKFLOW"
            if lose_credential:
                raise httpx.ReadTimeout("lost credential response")
            return {"id": "header-fixed", "name": payload["name"], "type": payload["type"]}
        if path == "/api/v1/workflows":
            state.update(
                **payload,
                id="wf-fixed",
                versionId=str(uuid.uuid4()),
                active=False,
                activeVersionId=None,
            )
            if lose_workflow:
                raise httpx.ReadTimeout("lost workflow response")
            return copy.deepcopy(state)
        if path.startswith("/api/v1/workflows?"):
            return {"data": [copy.deepcopy(state)]}
        if path.endswith("/activate"):
            assert payload == {"versionId": state["versionId"]}
            state.update(active=True, activeVersionId=state["versionId"])
            if lose_activation:
                raise httpx.ReadTimeout("lost activation response")
            return copy.deepcopy(state)
        assert path == "/api/v1/workflows/wf-fixed"
        return copy.deepcopy(state)

    mp.setattr("hub.workflow_operator.remote", remote)
    return t, b, a, calls, state


def test_action_granted_provision_and_activation(workflows):
    app, c, h, _ = workflows
    t, b, a, calls, state = operator_setup(workflows)
    path = "/api/actions/" + a["id"] + "/execute"
    r = c.post(path, headers=h, json={})
    assert r.status_code == 200, r.text
    assert r.json()["receipt"]["status"] == "verified"
    assert c.post(path, headers=h, json={}).json() == r.json()
    assert len([call for call in calls if call[1]]) == 2
    a2 = action(c, h, t, b, "n8n.workflow.activate", state["versionId"])
    r = c.post("/api/actions/" + a2["id"] + "/execute", headers=h, json={})
    assert r.status_code == 200, r.text
    assert r.json()["receipt"]["status"] == "ready"
    assert len([call for call in calls if call[1]]) == 3


@pytest.mark.parametrize("which", ["credential", "workflow", "activation"])
def test_lost_write_response_is_reconciled_without_repost(workflows, which):
    app, c, h, _ = workflows
    t, b, a, calls, state = operator_setup(workflows, **{"lose_" + which: True})
    path = "/api/actions/" + a["id"] + "/execute"
    r = c.post(path, headers=h, json={})
    assert r.status_code == 200, r.text
    if which == "activation":
        a = action(c, h, t, b, "n8n.workflow.activate", state["versionId"])
        path = "/api/actions/" + a["id"] + "/execute"
        r = c.post(path, headers=h, json={})
    assert r.json()["status"] == "uncertain"
    count = len([call for call in calls if call[1]])
    r2 = c.post(path, headers=h, json={})
    assert r2.status_code == (409 if which == "credential" else 200), r2.text
    if which != "credential":
        assert r2.json()["status"] == "succeeded"
    assert len([call for call in calls if call[1]]) == count


def test_pause_between_stages_stops_next_write(workflows):
    import hub.workflow_operator as operator

    app, c, h, mp = workflows
    t, b, a, calls, state = operator_setup(workflows)
    original, count = operator.gate, 0

    def stop(db, aid):
        nonlocal count
        count += 1
        if count == 3:
            policy = c.get("/api/action-policy").json()
            assert (
                c.patch(
                    "/api/action-policy",
                    headers=h,
                    json={"paused": True, "expected_revision": policy["revision"]},
                ).status_code
                == 200
            )
        return original(db, aid)

    mp.setattr(operator, "gate", stop)
    r = c.post("/api/actions/" + a["id"] + "/execute", headers=h, json={})
    assert r.status_code == 403, r.text
    assert [p for p, write in calls if write] == ["/api/v1/credentials"]
    with app.state.sessions() as db:
        assert db.get(WorkflowBinding, b["id"]).status == "credential_ready"


def test_cancel_unknown_dispatch_blocks_late_callback(workflows):
    app, c, h, mp = workflows
    t, b, token, calls, state = ready(workflows)
    mp.setattr("hub.workflow_api.remote", lambda cfg, path, **kw: state)
    body = run_body(t)
    c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=body)
    cancelled = c.post(
        "/api/workflow-dispatches/" + body["request_id"] + "/cancel", headers=h, json={}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["dispatches"][0]["status"] == "cancelled"
    r = c.post(
        "/api/workflow-callback/" + b["id"],
        headers={"X-OBDAAI-WORKFLOW": token},
        json={"dispatch_id": body["request_id"], "execution_id": "42"},
    )
    assert r.status_code == 409


def test_operational_completion_query_is_bound_and_excludes_private_results(workflows):
    app, c, h, _ = workflows
    t, b, token, calls, state = ready(workflows)
    r = c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=run_body(t))
    r.raise_for_status()
    d = r.json()["dispatches"][0]
    terminal(c, t)
    body = {"dispatch_id": d["id"], "execution_id": "42"}
    endpoint = "/api/workflow-status/" + b["id"]
    assert c.post(endpoint, json=body).status_code == 401
    good = c.post(endpoint, headers={"X-OBDAAI-WORKFLOW": token}, json=body)
    assert good.status_code == 200, good.text
    assert good.json()["complete"] and good.json()["succeeded"]
    assert set(good.json()) == {"dispatch_id", "execution_id", "run_id", "complete", "succeeded"}
    assert "PRIVATE_TASK" not in good.text and "sources" not in good.text
    assert (
        c.post(
            endpoint, headers={"X-OBDAAI-WORKFLOW": token}, json=body | {"execution_id": "43"}
        ).status_code
        == 409
    )
    control(c, h, t, paused=True)
    assert c.post(endpoint, headers={"X-OBDAAI-WORKFLOW": token}, json=body).status_code == 409


def test_completion_response_is_verified_against_bound_run_not_arbitrary_remote_claim(workflows):
    app, c, h, mp = workflows
    t, b, token, calls, state = ready(workflows, workflow_wait=True)
    original = __import__("hub.workflow_api", fromlist=["remote"]).remote

    def remote(cfg, path, **kwargs):
        result = original(cfg, path, **kwargs)
        if path.startswith("/webhook/"):
            terminal(c, t)
            return result | {"complete": True, "succeeded": True}
        return result

    mp.setattr("hub.workflow_api.remote", remote)
    result = c.post("/api/workflows/" + b["id"] + "/runs", headers=h, json=run_body(t))
    assert result.status_code == 200, result.text
    assert result.json()["dispatches"][0]["status"] == "completed"
