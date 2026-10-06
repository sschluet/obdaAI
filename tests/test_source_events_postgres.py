"""Real PG event cursor, queue atomicity, concurrent pulses and worker receipt."""

import asyncio
import concurrent.futures
import os
import time

import pytest
from alembic import command
from alembic.config import Config
from hub.action_api import digest, encode
from hub.config import Settings
from hub.db import (
    Project,
    Source,
    SourceReadyEvent,
    Task,
    TaskEventOccurrence,
    TaskRevision,
    TaskRun,
    TaskSchedule,
    TaskStep,
    session_factory,
)
from hub.jobs import worker_app
from hub.schedule_api import ScheduleDefinition, tick
from hub.source_events import record_ready
from hub.task_api import TaskSpec, lock
from sqlalchemy import delete, func, select, text


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG fixture required")
def test_document_event_queue_cursor_and_duplicate_delivery(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only loopback hub_ci is allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    cfg = Settings(database_url=url)
    factory = session_factory(url)
    now = time.time()
    with factory() as db:
        lock(db)
        project = Project(name="Synthetic document event")
        task = Task(paused=False)
        db.add_all([project, task])
        db.flush()
        pid, tid = project.id, task.id
        document = encode(
            TaskSpec(
                title="Document-ready read", goal="Count local resources", project_id=pid
            ).model_dump(mode="json")
        )
        db.add(TaskRevision(task_id=tid, revision=1, spec=document, sha256=digest(document)))
        db.add(
            TaskSchedule(
                task_id=tid,
                revision=1,
                task_revision=1,
                control_revision=1,
                spec_sha256=digest(document),
                definition=encode(
                    ScheduleDefinition(kind="source_ready", time="09:00").model_dump(mode="json")
                ),
                paused=False,
                event_cursor=0,
            )
        )
        source = Source(
            project_id=pid, name="synthetic.txt", sha256="c" * 64, size=1, status="ready"
        )
        db.add(source)
        db.flush()
        sid = source.id
        record_ready(db, source)
        db.flush()
        event = db.scalar(select(SourceReadyEvent).where(SourceReadyEvent.source_id == sid))
        event.created = now
        db.commit()
    try:
        with factory() as db:
            lock(db)
            assert len(tick(db, cfg, now + 1)) == 1
            db.rollback()
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(TaskEventOccurrence)
                    .where(TaskEventOccurrence.task_id == tid)
                )
                == 0
            )
            assert db.get(TaskSchedule, tid).event_cursor == 0

        def pulse(_):
            with factory() as db:
                lock(db)
                jobs = tick(db, cfg, now + 1)
                db.commit()
                return jobs

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            batches = list(pool.map(pulse, range(4)))
        assert sum(map(len, batches)) == 1
        queue = worker_app(cfg)

        async def work():
            async with queue.open_async():
                await queue.run_worker_async(
                    queues=["tasks"], wait=False, install_signal_handlers=False, concurrency=2
                )

        asyncio.run(work())
        with factory() as db:
            occurrence = db.scalar(
                select(TaskEventOccurrence).where(TaskEventOccurrence.task_id == tid)
            )
            assert db.get(TaskRun, occurrence.run_id).status == "succeeded"
            assert db.get(TaskSchedule, tid).event_cursor == occurrence.event_id
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(TaskStep)
                    .where(TaskStep.run_id == occurrence.run_id)
                )
                == 1
            )
        assert pulse(None) == []
    finally:
        with factory() as db:
            db.execute(text("SET LOCAL search_path TO hub_queue, public"))
            db.execute(
                text(
                    "DELETE FROM hub_queue.procrastinate_jobs WHERE task_name='hub.task-read' "
                    "AND args->>'run_id' IN (SELECT id FROM task_runs WHERE task_id=:tid)"
                ),
                {"tid": tid},
            )
            runs = select(TaskRun.id).where(TaskRun.task_id == tid)
            db.execute(delete(TaskStep).where(TaskStep.run_id.in_(runs)))
            db.execute(delete(TaskEventOccurrence).where(TaskEventOccurrence.task_id == tid))
            db.execute(delete(TaskSchedule).where(TaskSchedule.task_id == tid))
            db.execute(delete(TaskRun).where(TaskRun.task_id == tid))
            db.execute(delete(TaskRevision).where(TaskRevision.task_id == tid))
            db.execute(delete(Task).where(Task.id == tid))
            db.execute(delete(SourceReadyEvent).where(SourceReadyEvent.source_id == sid))
            db.execute(delete(Source).where(Source.id == sid))
            db.execute(delete(Project).where(Project.id == pid))
            db.commit()
