import concurrent.futures
import json
import time
import uuid

import pytest
import test_chat
from hub.action_api import digest, encode
from hub.db import TaskRun, TaskStep
from hub.task_api import execute_task_read
from sqlalchemy import func, select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def create(c, h, **changes):
    r = c.post(
        "/api/tasks",
        headers=h,
        json={"title": "Synthetic read task", "goal": "Count Hub resources", **changes},
    )
    assert r.status_code == 200, r.text
    return r.json()


def control(c, h, task, paused=False, archived=False):
    return c.patch(
        "/api/tasks/" + task["id"] + "/control",
        headers=h,
        json={
            "paused": paused,
            "archived": archived,
            "expected_revision": task["revision"],
            "expected_control_revision": task["control_revision"],
        },
    )


def run_body(task):
    return {
        "request_id": str(uuid.uuid4()),
        "expected_revision": task["revision"],
        "expected_control_revision": task["control_revision"],
        "spec_sha256": task["spec_sha256"],
    }


def terminal(c, task):
    for _ in range(100):
        r = c.get("/api/tasks/" + task["id"] + "/runs").json()
        if r and r[0]["status"] not in ("queued", "running"):
            return r[0]
        time.sleep(0.01)
    pytest.fail("Synthetic read worker did not finish")


def queued(app, task, **changes):
    snapshot = {
        "spec": task["spec"],
        "skills_checked": [],
        "model": None,
        "cost_usd": 0,
        "label": "LOCAL_ONLY",
    }
    with app.state.sessions() as db:
        run = TaskRun(
            task_id=task["id"],
            task_revision=task["revision"],
            control_revision=task["control_revision"],
            request_key=str(uuid.uuid4()),
            request_digest=digest("synthetic"),
            snapshot=encode(snapshot),
            **changes,
        )
        db.add(run)
        db.commit()
        return run.id


def test_manual_lifecycle_receipt_duplicate_and_immutable_edit(setup):
    app, c, h, _ = setup
    task = create(c, h)
    assert task["paused"] and task["next_run"] is None
    assert (
        c.post("/api/tasks/" + task["id"] + "/runs", headers=h, json=run_body(task)).status_code
        == 409
    )
    task = control(c, h, task).json()
    body = run_body(task)
    result = c.post("/api/tasks/" + task["id"] + "/runs", headers=h, json=body)
    assert result.status_code == 200
    receipt = terminal(c, task)
    assert receipt["status"] == "succeeded" and receipt["snapshot"]["model"] is None
    assert receipt["snapshot"]["cost_usd"] == 0 and len(receipt["steps"]) == 1
    assert receipt["steps"][0]["result"]["label"] == "LOCAL_ONLY"
    assert (
        c.post("/api/tasks/" + task["id"] + "/runs", headers=h, json=body).json()["id"]
        == receipt["id"]
    )
    execute_task_read(app.state.sessions, receipt["id"])
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(TaskStep)) == 1
    spec = {**task["spec"], "title": "Changed synthetic task"}
    revised = c.patch(
        "/api/tasks/" + task["id"],
        headers=h,
        json={
            "spec": spec,
            "expected_revision": 1,
            "expected_control_revision": task["control_revision"],
        },
    ).json()
    assert revised["revision"] == 2 and revised["paused"]
    history = c.get("/api/tasks/" + task["id"] + "/revisions").json()
    assert len(history) == 2 and history[0]["spec"]["title"] == "Synthetic read task"
    assert control(c, h, task).status_code == 409
    archived = control(c, h, revised, True, True).json()
    assert archived["archived"]
    restored = control(c, h, archived, True, False).json()
    assert restored["paused"] and not restored["archived"]
    altered = {**body, "spec_sha256": "0" * 64}
    assert c.post("/api/tasks/" + task["id"] + "/runs", headers=h, json=altered).status_code == 409


@pytest.mark.parametrize(
    "changes",
    [
        {"steps": [{"tool_id": "project.archive"}]},
        {"steps": [{"parameters": {"url": "https://evil.example"}}]},
        {"autonomy": "autonomous"},
        {"trigger": "daily"},
        {"label": "CLOUD_ALLOWED"},
        {"max_cost_usd": 1},
        {"timezone": "../../etc/passwd"},
        {"credential": "secret"},
        {"steps": [{"tool_revision": 2}]},
        {"steps": []},
    ],
)
def test_tasks_cannot_inject_tools_schedule_code_or_permissions(setup, changes):
    _, c, h, _ = setup
    assert (
        c.post(
            "/api/tasks", headers=h, json={"title": "Synthetic", "goal": "Read", **changes}
        ).status_code
        == 422
    )


def test_pause_cancel_edit_and_duplicate_worker_last_boundary(setup):
    app, c, h, _ = setup
    task = control(c, h, create(c, h)).json()
    rid = queued(app, task)
    task = control(c, h, task, True).json()
    execute_task_read(app.state.sessions, rid)
    assert terminal(c, task)["status"] == "failed"
    task = control(c, h, task).json()
    rid = queued(app, task)
    assert (
        c.post("/api/task-runs/" + rid + "/cancel", headers=h, json={}).json()["status"]
        == "cancelled"
    )
    execute_task_read(app.state.sessions, rid)
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(TaskStep)) == 0
    rid = queued(app, task)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        list(pool.map(lambda _: execute_task_read(app.state.sessions, rid), range(4)))
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(TaskStep)) == 1


def test_skill_context_drift_scope_and_no_new_grants(setup):
    app, c, h, _ = setup
    p = c.post("/api/projects", headers=h, json={"name": "Synthetic task scope"}).json()
    doc = (
        "---\n"
        + json.dumps({"format": "obdaai-skill-1", "name": "Synthetic task binding"})
        + "\n---\nNo rights."
    )
    s = c.post("/api/skills", headers=h, json={"document": doc, "project_id": p["id"]}).json()
    c.post(
        "/api/skills/" + s["id"] + "/trust",
        headers=h,
        json={"expected_revision": 1, "sha256": s["sha256"], "enabled": True},
    )
    binding = {"id": s["id"], "revision": 1, "sha256": s["sha256"]}
    assert (
        c.post(
            "/api/tasks",
            headers=h,
            json={"title": "Wrong scope", "goal": "Read", "skills": [binding]},
        ).status_code
        == 409
    )
    task = control(c, h, create(c, h, project_id=p["id"], skills=[binding])).json()
    rid = queued(app, task)
    c.post(
        "/api/skills/" + s["id"] + "/trust",
        headers=h,
        json={"expected_revision": 1, "sha256": s["sha256"], "enabled": False},
    )
    execute_task_read(app.state.sessions, rid)
    assert terminal(c, task)["status"] == "failed"


def test_task_auth_csrf_and_tampered_run_snapshot(setup):
    app, c, h, _ = setup
    assert c.post("/api/tasks", json={"title": "Synthetic", "goal": "Read"}).status_code == 403
    task = control(c, h, create(c, h)).json()
    rid = queued(app, task)
    with app.state.sessions() as db:
        r = db.get(TaskRun, rid)
        snapshot = json.loads(r.snapshot)
        snapshot["spec"]["goal"] = "changed"
        r.snapshot = encode(snapshot)
        db.commit()
    execute_task_read(app.state.sessions, rid)
    assert terminal(c, task)["status"] == "failed"
    c.post("/api/logout", headers=h)
    assert c.get("/api/tasks").status_code == 401


@pytest.mark.parametrize("snapshot", ["{}", '["unexpected"]', '{"spec":null}'])
def test_corrupt_manifest_stops_without_a_read_receipt(setup, snapshot):
    app, c, h, _ = setup
    task = control(c, h, create(c, h)).json()
    rid = queued(app, task)
    with app.state.sessions() as db:
        db.get(TaskRun, rid).snapshot = snapshot
        db.commit()
    execute_task_read(app.state.sessions, rid)
    result = terminal(c, task)
    assert result["status"] == "failed" and result["error"] == "Laufvorgabe verändert"
    assert not result["steps"]


def test_task_listing_batches_history_and_preserves_schedule_and_grant_state(setup):
    from hub.db import Task, TaskRevision, TaskSchedule, TaskWriteGrant
    from hub.task_api import TaskSpec, task_info, task_listing
    from sqlalchemy import event

    app, c, h, _ = setup
    task = create(c, h)
    first = queued(
        app, task, status="succeeded", created=10, id="00000000-0000-4000-8000-000000000001"
    )
    latest = queued(
        app, task, status="failed", created=10, id="ffffffff-ffff-4fff-8fff-ffffffffffff"
    )
    assert first != latest
    with app.state.sessions() as db:
        db.add(
            TaskSchedule(
                task_id=task["id"],
                task_revision=1,
                control_revision=0,
                spec_sha256=task["spec_sha256"],
                definition=encode({"kind": "manual"}),
                paused=False,
                next_due=123,
            )
        )
        db.add(
            TaskWriteGrant(
                task_id=task["id"],
                task_revision=1,
                control_revision=1,
                spec_sha256=task["spec_sha256"],
                policy_revision=1,
                expires=123,
                used=True,
            )
        )
        for index in range(25):
            row = Task(created=20 + index, archived=bool(index % 2))
            db.add(row)
            db.flush()
            document = encode(
                TaskSpec(title=f"Batch {index}", goal="Read only").model_dump(mode="json")
            )
            db.add(TaskRevision(task_id=row.id, revision=1, spec=document, sha256=digest(document)))
        db.commit()
    statements = []
    with app.state.sessions() as db:
        engine = db.get_bind()

        def capture(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            listing = task_listing(db)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(statements) == 5
        assert listing == [task_info(db, item["id"]) for item in listing]
    assert len(listing) == 26
    tested = next(item for item in listing if item["id"] == task["id"])
    assert tested["last_run"]["id"] == latest
    assert tested["schedule"]["paused"] and tested["schedule"]["needs_review"]
    assert tested["write_grant"]["used"] and tested["write_grant"]["expires"] == 123
    with app.state.sessions() as db:
        db.get(TaskRevision, (task["id"], 1)).sha256 = "0" * 64
        db.commit()
    assert c.get("/api/tasks").status_code == 409
