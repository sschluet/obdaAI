import concurrent.futures
import time
from dataclasses import replace
from datetime import datetime

import pytest
import test_chat
import test_tasks
from hub.api import create_app
from hub.db import ScheduleOccurrence, TaskRun, TaskSchedule
from hub.schedule_api import ScheduleDefinition, next_due, tick
from hub.task_api import lock
from pydantic import ValidationError
from sqlalchemy import func, select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def put(c, h, task, **definition):
    return c.put(
        "/api/tasks/" + task["id"] + "/schedule",
        headers=h,
        json={
            "definition": {"kind": "daily", "time": "10:00", **definition},
            "expected_revision": task["revision"],
            "expected_control_revision": task["control_revision"],
            "spec_sha256": task["spec_sha256"],
            "expected_schedule_revision": (task.get("schedule") or {}).get("revision", 0),
        },
    )


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


def test_dst_wall_time_and_weekdays():
    daily = ScheduleDefinition(kind="daily", time="02:30")
    assert next_due(daily, stamp("2026-03-28T03:00:00+01:00")) == stamp("2026-03-30T02:30:00+02:00")
    assert next_due(daily, stamp("2026-10-24T03:00:00+02:00")) == stamp("2026-10-25T02:30:00+02:00")
    assert next_due(daily, stamp("2026-10-25T02:35:00+02:00")) == stamp("2026-10-26T02:30:00+01:00")
    weekly = ScheduleDefinition(kind="weekly", time="09:00", weekdays=[0, 4])
    assert next_due(weekly, stamp("2026-10-05T09:01:00+02:00")) == stamp(
        "2026-10-09T09:00:00+02:00"
    )
    for day in ["2026-03-29", "2026-10-25"]:
        with pytest.raises(ValidationError):
            ScheduleDefinition(kind="once", date=day, time="02:30")
    with pytest.raises(ValidationError):
        ScheduleDefinition(kind="weekly", time="09:00", weekdays=[0, 0])


def test_save_permissions_conflict_and_disabled_activation(setup):
    app, c, h, _ = setup
    t = test_tasks.create(c, h)
    assert put(c, {}, t).status_code == 403
    saved = put(c, h, t)
    assert saved.status_code == 200, saved.text
    t = saved.json()
    assert t["paused"] and t["schedule"]["paused"] and t["next_run"] > time.time()
    assert put(c, h, {**t, "schedule": None}).status_code == 409
    body = {
        "expected_schedule_revision": t["schedule"]["revision"],
        "expected_revision": t["revision"],
        "expected_control_revision": t["control_revision"],
        "paused": False,
    }
    assert (
        c.patch("/api/tasks/" + t["id"] + "/schedule/control", headers=h, json=body).status_code
        == 409
    )
    assert c.get("/api/scheduler/status").json()["configured"] is False
    assert c.post("/api/scheduler/tick", json={}).status_code == 503
    assert not c.get("/api/tasks/" + t["id"] + "/runs").json()


def armed(app, c, h, due):
    task = test_tasks.control(c, h, test_tasks.create(c, h)).json()
    task = put(c, h, task).json()
    with app.state.sessions() as db:
        plan = db.get(TaskSchedule, task["id"])
        plan.paused = False
        plan.next_due = due
        db.commit()
    return task


def pulse(app, now):
    with app.state.sessions() as db:
        lock(db)
        jobs = tick(db, app.state.settings, now)
        db.commit()
        return jobs


def test_atomic_duplicate_clock_and_receipt_restart(setup):
    app, c, h, _ = setup
    now = time.time()
    t = armed(app, c, h, now - 30)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: pulse(app, now), range(4)))
    assert sum(map(len, jobs)) == 1
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ScheduleOccurrence)) == 1
        run = db.scalar(select(TaskRun))
        assert run.task_revision == t["revision"]
        run_id = run.id
    test_tasks.execute_task_read(app.state.sessions, run_id)
    history = c.get("/api/tasks/" + t["id"] + "/schedule/history").json()
    assert history[0]["run_id"] == run_id
    assert c.get("/api/tasks/" + t["id"] + "/runs").json()[0]["status"] == "succeeded"
    assert pulse(app, now) == []


def test_late_overlap_and_task_drift_are_retained(setup):
    app, c, h, _ = setup
    now = time.time()
    late = armed(app, c, h, now - 500)
    overlap = armed(app, c, h, now - 20)
    test_tasks.queued(app, overlap)
    changed = armed(app, c, h, now - 20)
    test_tasks.control(c, h, changed, paused=True)
    assert pulse(app, now) == []
    histories = [
        c.get("/api/tasks/" + t["id"] + "/schedule/history").json()[0]
        for t in [late, overlap, changed]
    ]
    assert [x["status"] for x in histories] == ["skipped", "skipped", "blocked"]
    assert all(x["reason"] and x["run_id"] is None for x in histories)
    assert c.get("/api/tasks").json()[0]["schedule"]["paused"]


def test_machine_token_has_only_clock_access(setup, tmp_path):
    app, _, _, _ = setup
    path = tmp_path / "clock.key"
    path.write_text("synthetic-clock-token-12345678901234567890")
    path.chmod(0o600)
    cfg = replace(app.state.settings, scheduler_enabled=True, scheduler_token_file=str(path))
    application = create_app(cfg)
    from fastapi.testclient import TestClient

    with TestClient(application) as c:
        assert c.post("/api/scheduler/tick", json={}).status_code == 401
        header = {"Authorization": "Bearer " + path.read_text()}
        assert c.post("/api/scheduler/tick", headers=header, json={}).json() == {"queued": 0}
        assert c.get("/api/tasks", headers=header).status_code == 401
        assert (
            c.post(
                "/api/scheduler/tick", headers=header, json={"url": "http://attacker"}
            ).status_code
            == 422
        )
        assert c.get("/api/scheduler/status", headers=header).status_code == 401


def test_healthy_clock_activation_pause_manual_and_immutable_plan_revisions(setup, tmp_path):
    from fastapi.testclient import TestClient
    from hub.db import ScheduleRevision, SchedulerPulse

    app, original, h, _ = setup
    task = put(original, h, test_tasks.create(original, h)).json()
    path = tmp_path / "clock.key"
    path.write_text("synthetic-clock-token-12345678901234567890")
    path.chmod(0o600)
    cfg = replace(app.state.settings, scheduler_enabled=True, scheduler_token_file=str(path))
    with TestClient(create_app(cfg)) as c:
        c.cookies.update(original.cookies)
        clock_headers = {"Authorization": "Bearer " + path.read_text()}
        assert c.post("/api/scheduler/tick", headers=clock_headers, json={}).status_code == 200
        body = {
            "expected_schedule_revision": task["schedule"]["revision"],
            "expected_revision": task["revision"],
            "expected_control_revision": task["control_revision"],
            "paused": False,
        }
        activated = c.patch("/api/tasks/" + task["id"] + "/schedule/control", headers=h, json=body)
        assert activated.status_code == 200, activated.text
        task = activated.json()
        assert not task["paused"] and not task["schedule"]["paused"]
        assert (
            c.patch(
                "/api/tasks/" + task["id"] + "/schedule/control", headers=h, json=body
            ).status_code
            == 409
        )
        # Explicitly switching back to manual retains the old plan and its history.
        task = put(c, h, task, kind="manual").json()
        assert task["schedule"]["paused"] and task["next_run"] is None
        assert not c.get("/api/tasks/" + task["id"] + "/runs").json()
        with app.state.sessions() as db:
            revisions = list(
                db.scalars(
                    select(ScheduleRevision)
                    .where(ScheduleRevision.task_id == task["id"])
                    .order_by(ScheduleRevision.revision)
                )
            )
            assert len(revisions) == 3
            assert "daily" in revisions[0].snapshot and "manual" in revisions[-1].snapshot
            db.get(SchedulerPulse, 1).last_tick = time.time() - 600
            db.commit()
        assert c.get("/api/scheduler/status").json()["healthy"] is False


def test_schedule_pause_revokes_queued_run_at_worker_boundary(setup):
    app, c, h, _ = setup
    now = time.time()
    task = armed(app, c, h, now - 10)
    jobs = pulse(app, now)
    assert len(jobs) == 1
    body = {
        "expected_schedule_revision": task["schedule"]["revision"],
        "expected_revision": task["revision"],
        "expected_control_revision": task["control_revision"],
        "paused": True,
    }
    paused = c.patch("/api/tasks/" + task["id"] + "/schedule/control", headers=h, json=body)
    assert paused.status_code == 200, paused.text
    test_tasks.execute_task_read(app.state.sessions, jobs[0])
    result = c.get("/api/tasks/" + task["id"] + "/runs").json()[0]
    assert result["status"] == "failed" and not result["steps"]
    assert "Zeitplan pausiert" in result["error"]
    assert c.get("/api/tasks/" + task["id"] + "/schedule/history").json()[0]["status"] == "failed"


def test_scheduled_model_does_not_start_after_plan_pause(setup):
    import asyncio

    from hub.task_model import execute_task
    from test_task_model import AnalysisProvider

    app, c, h, _ = setup
    now = time.time()
    task = test_tasks.control(
        c, h, test_tasks.create(c, h, steps=[{"tool_id": "ai.analyze"}])
    ).json()
    task = put(c, h, task).json()
    with app.state.sessions() as db:
        plan = db.get(TaskSchedule, task["id"])
        plan.paused = False
        plan.next_due = now - 10
        db.commit()
    jobs = pulse(app, now)
    with app.state.sessions() as db:
        db.get(TaskSchedule, task["id"]).paused = True
        db.commit()
    provider = AnalysisProvider()
    asyncio.run(execute_task(app.state.sessions, app.state.settings, jobs[0], provider))
    result = c.get("/api/tasks/" + task["id"] + "/runs").json()[0]
    assert result["status"] == "failed" and not provider.stream_calls
