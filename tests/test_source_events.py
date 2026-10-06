import concurrent.futures
import time

import pytest
import test_chat
import test_schedules
import test_tasks
from hub.db import Project, Source, SourceReadyEvent, TaskEventOccurrence, TaskRun, TaskSchedule
from hub.source_events import latest_event, record_ready
from hub.task_api import lock
from sqlalchemy import func, select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def project(c, h):
    r = c.post("/api/projects", headers=h, json={"name": "Synthetic event scope"})
    assert r.status_code == 200
    return r.json()["id"]


def ready(app, pid, now, *, retry_id=None):
    with app.state.sessions() as db:
        lock(db)
        source = (
            db.get(Source, retry_id)
            if retry_id
            else Source(
                project_id=pid,
                name="Synthetic metadata only.txt",
                sha256="a" * 64,
                size=1,
                status="ready",
                label="LOCAL_ONLY",
            )
        )
        if not retry_id:
            db.add(source)
            db.flush()
        record_ready(db, source)
        db.flush()
        event = db.scalar(select(SourceReadyEvent).where(SourceReadyEvent.source_id == source.id))
        event.created = now
        sid, eid = source.id, event.id
        db.commit()
        return sid, eid


def armed(app, c, h, pid):
    task = test_tasks.control(c, h, test_tasks.create(c, h, project_id=pid)).json()
    result = test_schedules.put(c, h, task, kind="source_ready")
    assert result.status_code == 200, result.text
    task = result.json()
    with app.state.sessions() as db:
        plan = db.get(TaskSchedule, task["id"])
        plan.paused = False
        plan.event_cursor = latest_event(db)
        db.commit()
    return task


def test_event_is_local_unique_restart_safe_and_never_backfills(setup):
    app, c, h, cfg = setup
    now = time.time()
    pid = project(c, h)
    ready(app, pid, now - 60)
    task = armed(app, c, h, pid)
    sid, eid = ready(app, pid, now)
    ready(app, project(c, h), now)
    ready(app, pid, now, retry_id=sid)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda _: test_schedules.pulse(app, now + 1), range(4)))
    jobs = [j for batch in batches for j in batch]
    assert len(jobs) == 1
    test_tasks.execute_task_read(app.state.sessions, jobs[0])
    assert test_schedules.pulse(app, now + 2) == []
    runs = c.get("/api/tasks/" + task["id"] + "/runs").json()
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["snapshot"]["spec"]["sources"] == []
    history = c.get("/api/tasks/" + task["id"] + "/schedule/history").json()
    assert len(history) == 1 and history[0]["event"]["id"] == eid
    assert history[0]["event"]["source_id"] == sid and history[0]["status"] == "succeeded"
    assert "name" not in history[0]["event"] and "content" not in history[0]["event"]
    assert not c.get("/api/tasks").json()[0]["schedule"]["completed"]


@pytest.mark.parametrize("change", ["source", "pause", "project"])
def test_event_authority_is_rechecked_at_final_worker_boundary(setup, change):
    app, c, h, cfg = setup
    now = time.time()
    pid = project(c, h)
    task = armed(app, c, h, pid)
    sid, _ = ready(app, pid, now)
    jobs = test_schedules.pulse(app, now + 1)
    assert len(jobs) == 1
    with app.state.sessions() as db:
        lock(db)
        if change == "source":
            db.get(Source, sid).sha256 = "b" * 64
        elif change == "pause":
            db.get(TaskSchedule, task["id"]).paused = True
        else:
            db.get(Project, pid).archived = True
        db.commit()
    test_tasks.execute_task_read(app.state.sessions, jobs[0])
    run = c.get("/api/tasks/" + task["id"] + "/runs").json()[0]
    assert run["status"] == "failed" and run["steps"] == []


def test_late_overlapping_events_have_receipts_and_do_not_queue_parallel_runs(setup):
    app, c, h, cfg = setup
    now = time.time()
    pid = project(c, h)
    task = armed(app, c, h, pid)
    ready(app, pid, now - 121)
    ready(app, pid, now)
    ready(app, pid, now)
    assert len(test_schedules.pulse(app, now + 1)) == 1
    history = c.get("/api/tasks/" + task["id"] + "/schedule/history").json()
    assert len(history) == 3
    assert sorted(o["status"] for o in history) == ["queued", "skipped", "skipped"]
    assert any("verpasst" in (o["reason"] or "") for o in history)
    assert any("parallel" in (o["reason"] or "") for o in history)
    assert test_schedules.pulse(app, now + 2) == []


def test_event_and_run_cursor_roll_back_together(setup):
    app, c, h, cfg = setup
    now = time.time()
    pid = project(c, h)
    armed(app, c, h, pid)
    ready(app, pid, now)
    from hub.schedule_api import tick

    with app.state.sessions() as db:
        lock(db)
        assert len(tick(db, app.state.settings, now + 1)) == 1
        db.rollback()
        assert db.scalar(select(func.count()).select_from(TaskEventOccurrence)) == 0
        assert db.scalar(select(func.count()).select_from(TaskRun)) == 0
    assert len(test_schedules.pulse(app, now + 1)) == 1


def test_event_subscription_requires_project_and_local_reads(setup):
    app, c, h, cfg = setup
    task = test_tasks.create(c, h)
    assert test_schedules.put(c, h, task, kind="source_ready").status_code == 422
    pid = project(c, h)
    task = test_tasks.create(c, h, project_id=pid, steps=[{"tool_id": "ha.inspect"}])
    assert test_schedules.put(c, h, task, kind="source_ready").status_code == 422


def test_activation_resets_event_cursor_and_pause_revokes_queued_work(setup, tmp_path):
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from hub.api import create_app

    app, original, h, provider = setup
    pid = project(original, h)
    task = test_tasks.create(original, h, project_id=pid)
    task = test_schedules.put(original, h, task, kind="source_ready").json()
    key = tmp_path / "clock.key"
    key.write_text("synthetic-clock-token-12345678901234567890")
    key.chmod(0o600)
    cfg = replace(app.state.settings, scheduler_enabled=True, scheduler_token_file=str(key))
    with TestClient(create_app(cfg)) as c:
        c.cookies.update(original.cookies)
        assert (
            c.post(
                "/api/scheduler/tick",
                headers={"Authorization": "Bearer " + key.read_text()},
                json={},
            ).status_code
            == 200
        )
        ready(app, pid, time.time())

        def control(task, paused):
            result = c.patch(
                "/api/tasks/" + task["id"] + "/schedule/control",
                headers=h,
                json={
                    "expected_schedule_revision": task["schedule"]["revision"],
                    "expected_revision": task["revision"],
                    "expected_control_revision": task["control_revision"],
                    "paused": paused,
                },
            )
            assert result.status_code == 200, result.text
            return result.json()

        task = control(task, False)
        assert not task["schedule"]["completed"] and test_schedules.pulse(app, time.time()) == []
        ready(app, pid, time.time())
        jobs = test_schedules.pulse(app, time.time())
        assert len(jobs) == 1
        task = control(task, True)
        test_tasks.execute_task_read(app.state.sessions, jobs[0])
        assert c.get("/api/tasks/" + task["id"] + "/runs").json()[0]["status"] == "failed"
        ready(app, pid, time.time())
        task = control(task, False)
        assert test_schedules.pulse(app, time.time()) == []
        ready(app, pid, time.time())
        assert len(test_schedules.pulse(app, time.time())) == 1


def test_migration_baselines_existing_ready_originals_without_emitting_new_events(
    tmp_path, monkeypatch
):
    from alembic import command
    from alembic.config import Config
    from hub.db import session_factory

    url = "sqlite:///" + str(tmp_path / "before-events.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "0021")
    factory = session_factory(url)
    with factory() as db:
        p = Project(name="Existing original baseline")
        db.add(p)
        db.flush()
        s = Source(project_id=p.id, name="existing.txt", sha256="f" * 64, size=1, status="ready")
        db.add(s)
        db.flush()
        sid = s.id
        db.commit()
    command.upgrade(config, "head")
    with factory() as db:
        lock(db)
        events = list(db.scalars(select(SourceReadyEvent)))
        assert len(events) == 1 and events[0].baseline and events[0].source_id == sid
        source = db.get(Source, sid)
        source.revision += 1
        record_ready(db, source)
        db.commit()
    with factory() as db:
        events = list(db.scalars(select(SourceReadyEvent)))
        assert len(events) == 1 and events[0].baseline


@pytest.mark.parametrize("drift", [False, True])
def test_event_analysis_keeps_explicit_sources_and_rechecks_trigger_during_stream(setup, drift):
    import asyncio

    from hub.db import SourceChunk
    from hub.task_model import execute_task
    from test_task_model import AnalysisProvider

    app, c, h, provider = setup
    now = time.time()
    pid = project(c, h)
    selected, _ = ready(app, pid, now - 20)
    with app.state.sessions() as db:
        db.add(
            SourceChunk(
                source_id=selected,
                locator="Selected paragraph",
                content="EXPLICIT_SELECTED_SENTINEL",
            )
        )
        db.commit()
    task = test_tasks.control(
        c,
        h,
        test_tasks.create(
            c,
            h,
            project_id=pid,
            sources=[{"id": selected, "revision": 1, "sha256": "a" * 64}],
            steps=[{"tool_id": "ai.analyze"}],
        ),
    ).json()
    task = test_schedules.put(c, h, task, kind="source_ready").json()
    with app.state.sessions() as db:
        plan = db.get(TaskSchedule, task["id"])
        plan.paused = False
        plan.event_cursor = latest_event(db)
        db.commit()
    trigger, _ = ready(app, pid, now)
    with app.state.sessions() as db:
        db.add(
            SourceChunk(
                source_id=trigger,
                locator="Unselected paragraph",
                content="UNAPPROVED_NEW_DOCUMENT_SENTINEL",
            )
        )
        db.commit()
    jobs = test_schedules.pulse(app, now + 1)
    assert len(jobs) == 1

    class EventProvider(AnalysisProvider):
        async def stream(self, parts, roles, *, external, grants):
            async for piece in super().stream(parts, roles, external=external, grants=grants):
                yield piece
                if drift:
                    with app.state.sessions() as db:
                        lock(db)
                        db.get(Source, trigger).revision += 1
                        db.commit()

    model = EventProvider()
    asyncio.run(execute_task(app.state.sessions, app.state.settings, jobs[0], model))
    run = c.get("/api/tasks/" + task["id"] + "/runs").json()[0]
    assert run["status"] == ("failed" if drift else "succeeded")
    combined = "\n".join(part.content for part in model.parts)
    assert (
        "EXPLICIT_SELECTED_SENTINEL" in combined
        and "UNAPPROVED_NEW_DOCUMENT_SENTINEL" not in combined
        and trigger not in combined
    )
    assert model.stream_calls == [False]
    asyncio.run(execute_task(app.state.sessions, app.state.settings, jobs[0], model))
    assert model.stream_calls == [False]
