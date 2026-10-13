"""Real transactions for task approval, revocation and local write replay."""

import concurrent.futures
import time

import pytest
import test_tasks
from hub.db import ActionGrant, ActionIntent, ActionReceipt, Project, TaskRun, TaskWriteGrant
from hub.task_api import execute_task_read
from sqlalchemy import func, select

setup = test_tasks.setup


def write_task(c, h, autonomy="confirm_each"):
    project = c.post("/api/projects", headers=h, json={"name": "Synthetic archive target"}).json()
    task = test_tasks.create(
        c,
        h,
        autonomy=autonomy,
        success_criterion="all_steps_completed",
        steps=[
            {"tool_id": "hub.inspect"},
            {
                "tool_id": "project.archive",
                "parameters": {
                    "project_id": project["id"],
                    "expected_revision": project["revision"],
                },
            },
        ],
    )
    task = test_tasks.control(c, h, task).json()
    return project, task


def unpause(c, h):
    policy = c.get("/api/action-policy").json()
    return c.patch(
        "/api/action-policy",
        headers=h,
        json={"paused": False, "expected_revision": policy["revision"]},
    ).json()


def authority(c, task, **extra):
    return {
        "task_revision": task["revision"],
        "control_revision": task["control_revision"],
        "spec_sha256": task["spec_sha256"],
        "policy_revision": c.get("/api/action-policy").json()["revision"],
        **extra,
    }


def start(c, h, task):
    result = c.post("/api/tasks/" + task["id"] + "/runs", headers=h, json=test_tasks.run_body(task))
    assert result.status_code == 200, result.text
    return result.json()


def test_confirmation_wait_survives_reload_no_model_no_direct_gateway_bypass(setup):
    app, c, h, provider = setup
    project, task = write_task(c, h)
    run = start(c, h, task)
    assert run["status"] == "awaiting_approval"
    execute_task_read(app.state.sessions, run["id"])
    saved = c.get("/api/tasks/" + task["id"] + "/runs").json()[0]
    assert saved["status"] == "awaiting_approval" and not saved["steps"]
    action = saved["approval"]["actions"][0]
    assert (
        c.post("/api/actions/" + action["id"] + "/execute", headers=h, json={}).status_code == 409
    )
    assert (
        c.post(
            "/api/actions/" + action["id"] + "/grant",
            headers=h,
            json={"parameters_sha256": action["parameters_sha256"], "tool_revision": 1},
        ).status_code
        == 409
    )
    assert (
        c.post(
            "/api/task-runs/" + run["id"] + "/approve", headers=h, json=authority(c, task)
        ).status_code
        == 409
    )
    unpause(c, h)
    result = c.post("/api/task-runs/" + run["id"] + "/approve", headers=h, json=authority(c, task))
    assert result.status_code == 200, result.text
    receipt = test_tasks.terminal(c, task)
    assert receipt["status"] == "succeeded"
    assert receipt["steps"][-1]["result"]["project_id"] == project["id"]
    assert receipt["approval"]["actions"][0]["status"] == "succeeded"
    assert provider.calls == 0 and provider.stream_calls == []
    with concurrent.futures.ThreadPoolExecutor() as pool:
        list(pool.map(lambda _: execute_task_read(app.state.sessions, run["id"]), range(4)))
    with app.state.sessions() as db:
        assert db.get(Project, project["id"]).revision == project["revision"] + 1
        assert db.scalar(select(func.count()).select_from(ActionReceipt)) == 1
    assert (
        c.post(
            "/api/task-runs/" + run["id"] + "/approve", headers=h, json=authority(c, task)
        ).status_code
        == 409
    )


async def no_worker(*args, **kwargs):
    return


@pytest.mark.parametrize(
    "reason", ["expiry", "revoke", "pause", "target", "edit", "manifest", "action"]
)
def test_confirmation_final_boundary_and_atomic_rollback(setup, monkeypatch, reason):
    app, c, h, _ = setup
    monkeypatch.setattr("hub.task_model.execute_task", no_worker)
    unpause(c, h)
    project, task = write_task(c, h)
    run = start(c, h, task)
    approved = c.post(
        "/api/task-runs/" + run["id"] + "/approve", headers=h, json=authority(c, task)
    )
    assert approved.status_code == 200, approved.text
    with app.state.sessions() as db:
        row = db.get(TaskRun, run["id"])
        action = db.get(ActionIntent, run["approval"]["actions"][0]["id"])
        grant = db.get(ActionGrant, action.id)
        if reason == "expiry":
            grant.expires = time.time() - 1
        if reason == "revoke":
            grant.revoked = True
        if reason == "target":
            db.get(Project, project["id"]).revision += 1
        if reason == "manifest":
            row.snapshot = "{}"
        if reason == "action":
            action.parameters_sha256 = "0" * 64
        db.commit()
    if reason == "pause":
        policy = c.get("/api/action-policy").json()
        c.patch(
            "/api/action-policy",
            headers=h,
            json={"paused": True, "expected_revision": policy["revision"]},
        )
    if reason == "edit":
        test_tasks.control(c, h, task, True)
    execute_task_read(app.state.sessions, run["id"])
    receipt = test_tasks.terminal(c, task)
    assert receipt["status"] == "failed" and not receipt["steps"]
    with app.state.sessions() as db:
        assert not db.get(Project, project["id"]).archived
        assert db.scalar(select(func.count()).select_from(ActionReceipt)) == 0


def test_bounded_authority_requires_explicit_grant_and_is_consumed_once(setup):
    app, c, h, _ = setup
    unpause(c, h)
    project, task = write_task(c, h, "bounded_autonomous")
    assert (
        c.post(
            "/api/tasks/" + task["id"] + "/runs", headers=h, json=test_tasks.run_body(task)
        ).status_code
        == 403
    )
    granted = c.post(
        "/api/tasks/" + task["id"] + "/write-grant", headers=h, json=authority(c, task)
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["write_grant"]["max_writes"] == 1
    assert (
        c.post(
            "/api/tasks/" + task["id"] + "/write-grant", headers=h, json=authority(c, task)
        ).status_code
        == 409
    )
    run = start(c, h, task)
    assert test_tasks.terminal(c, task)["status"] == "succeeded"
    with app.state.sessions() as db:
        assert db.get(TaskWriteGrant, task["id"]).used
        assert db.get(Project, project["id"]).archived
        assert db.scalar(select(func.count()).select_from(ActionReceipt)) == 1
    execute_task_read(app.state.sessions, run["id"])
    assert c.post(
        "/api/tasks/" + task["id"] + "/runs", headers=h, json=test_tasks.run_body(task)
    ).status_code in (403, 409)


@pytest.mark.parametrize("reason", ["expiry", "revoke", "pause", "target", "edit"])
def test_bounded_authority_final_worker_gate(setup, monkeypatch, reason):
    app, c, h, _ = setup
    monkeypatch.setattr("hub.task_model.execute_task", no_worker)
    unpause(c, h)
    project, task = write_task(c, h, "bounded_autonomous")
    assert (
        c.post(
            "/api/tasks/" + task["id"] + "/write-grant", headers=h, json=authority(c, task)
        ).status_code
        == 200
    )
    run = start(c, h, task)
    with app.state.sessions() as db:
        if reason == "expiry":
            db.get(TaskWriteGrant, task["id"]).expires = time.time() - 1
        if reason == "target":
            db.get(Project, project["id"]).revision += 1
        db.commit()
    if reason == "revoke":
        c.post("/api/tasks/" + task["id"] + "/write-grant/revoke", headers=h, json={})
    if reason == "edit":
        test_tasks.control(c, h, task, True)
    if reason == "pause":
        p = c.get("/api/action-policy").json()
        c.patch(
            "/api/action-policy",
            headers=h,
            json={"paused": True, "expected_revision": p["revision"]},
        )
    execute_task_read(app.state.sessions, run["id"])
    assert test_tasks.terminal(c, task)["status"] == "failed"
    with app.state.sessions() as db:
        assert not db.get(Project, project["id"]).archived
        assert not db.get(TaskWriteGrant, task["id"]).used


def test_cancel_pending_confirmation_frees_active_slot_and_revoked_action_cannot_write(setup):
    app, c, h, _ = setup
    _, task = write_task(c, h)
    run = start(c, h, task)
    assert (
        c.post(
            "/api/tasks/" + task["id"] + "/runs", headers=h, json=test_tasks.run_body(task)
        ).status_code
        == 409
    )
    assert (
        c.post("/api/task-runs/" + run["id"] + "/cancel", headers=h, json={}).json()["status"]
        == "cancelled"
    )
    assert start(c, h, task)["status"] == "awaiting_approval"
    unpause(c, h)
    assert (
        c.post(
            "/api/task-runs/" + run["id"] + "/approve", headers=h, json=authority(c, task)
        ).status_code
        == 409
    )
    execute_task_read(app.state.sessions, run["id"])


def test_profiles_do_not_allow_model_permissions_arbitrary_tools_or_extra_writes(setup):
    _, c, h, _ = setup
    project, task = write_task(c, h)
    spec = task["spec"]
    for changed in (
        {"autonomy": "analyze_only"},
        {"max_cost_usd": 1},
        {"steps": [{"tool_id": "ha.update", "parameters": {}}]},
        {"steps": [spec["steps"][-1], spec["steps"][-1]]},
        {"steps": [spec["steps"][-1], {"tool_id": "ai.analyze"}]},
        {"project_id": project["id"]},
    ):
        assert c.post("/api/tasks", headers=h, json={**spec, **changed}).status_code == 422
    assert (
        c.post("/api/tasks/" + task["id"] + "/write-grant", json=authority(c, task)).status_code
        == 403
    )


def test_timeout_after_local_effect_rolls_back_effect_grant_and_receipts(setup, monkeypatch):
    from types import SimpleNamespace

    app, c, h, _ = setup
    monkeypatch.setattr("hub.task_model.execute_task", no_worker)
    unpause(c, h)
    project, task = write_task(c, h, "bounded_autonomous")
    assert (
        c.post(
            "/api/tasks/" + task["id"] + "/write-grant", headers=h, json=authority(c, task)
        ).status_code
        == 200
    )
    run = start(c, h, task)
    clock = iter([0, 0, 0, 0, 999])
    monkeypatch.setattr(
        "hub.task_api.time", SimpleNamespace(monotonic=lambda: next(clock), time=time.time)
    )
    execute_task_read(app.state.sessions, run["id"])
    result = test_tasks.terminal(c, task)
    assert result["status"] == "failed" and not result["steps"]
    with app.state.sessions() as db:
        assert not db.get(Project, project["id"]).archived
        assert not db.get(TaskWriteGrant, task["id"]).used
        assert db.scalar(select(func.count()).select_from(ActionReceipt)) == 0


def test_unused_grant_revocation_keeps_immutable_history(setup):
    from hub.db import TaskWriteGrantEvent

    app, c, h, _ = setup
    unpause(c, h)
    _, task = write_task(c, h, "bounded_autonomous")
    path = "/api/tasks/" + task["id"] + "/write-grant"
    assert c.post(path, headers=h, json=authority(c, task)).status_code == 200
    assert c.post(path + "/revoke", headers=h, json={}).status_code == 200
    assert c.post(path, headers=h, json=authority(c, task)).status_code == 200
    history = c.get(path + "/history").json()
    assert [e["event"] for e in history] == ["granted", "revoked", "granted"]
    with app.state.sessions() as db:
        event = db.scalar(select(TaskWriteGrantEvent))
        event.document = "{}"
        db.commit()
    assert c.get(path + "/history").status_code == 409
