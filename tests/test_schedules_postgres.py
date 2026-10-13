"""Real PostgreSQL clock lock, queue rollback, duplicate wake-up and worker receipt."""

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
    ScheduleOccurrence,
    Task,
    TaskRevision,
    TaskRun,
    TaskSchedule,
    TaskStep,
    session_factory,
)
from hub.jobs import worker_app
from hub.schedule_api import ScheduleDefinition, tick
from hub.task_api import TaskSpec, lock
from sqlalchemy import delete, func, select, text


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG fixture required")
def test_clock_queue_transaction_and_duplicate_delivery(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only loopback hub_ci is allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    cfg = Settings(database_url=url)
    factory = session_factory(url)
    now = time.time()
    with factory() as db:
        task = Task(paused=False)
        db.add(task)
        db.flush()
        tid = task.id
        document = encode(
            TaskSpec(title="Synthetic scheduled read", goal="Count resources").model_dump(
                mode="json"
            )
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
                    ScheduleDefinition(kind="daily", time="09:00").model_dump(mode="json")
                ),
                paused=False,
                next_due=now - 10,
            )
        )
        db.commit()
    try:
        with factory() as db:
            lock(db)
            assert len(tick(db, cfg, now)) == 1
            db.rollback()
            assert (
                db.scalar(select(func.count()).select_from(TaskRun).where(TaskRun.task_id == tid))
                == 0
            )
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM hub_queue.procrastinate_jobs "
                        "WHERE task_name='hub.task-read'"
                    )
                )
                == 0
            )

        def wake(_):
            with factory() as db:
                lock(db)
                jobs = tick(db, cfg, now)
                db.commit()
                return jobs

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(wake, range(4)))
        assert sum(map(len, results)) == 1
        queue = worker_app(cfg)

        async def work():
            async with queue.open_async():
                await queue.run_worker_async(
                    queues=["tasks"], wait=False, install_signal_handlers=False, concurrency=2
                )

        asyncio.run(work())
        with factory() as db:
            occurrence = db.scalar(
                select(ScheduleOccurrence).where(ScheduleOccurrence.task_id == tid)
            )
            assert db.get(TaskRun, occurrence.run_id).status == "succeeded"
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(TaskStep)
                    .where(TaskStep.run_id == occurrence.run_id)
                )
                == 1
            )
    finally:
        with factory() as db:
            # Queue triggers use unqualified names; bind their schema for this transaction.
            db.execute(text("SET LOCAL search_path TO hub_queue, public"))
            # Remove only this fixture's completed queue audit before later PG tests.
            db.execute(
                text(
                    "DELETE FROM hub_queue.procrastinate_jobs WHERE task_name='hub.task-read' "
                    "AND args->>'run_id' IN (SELECT id FROM task_runs WHERE task_id=:tid)"
                ),
                {"tid": tid},
            )
            runs = select(TaskRun.id).where(TaskRun.task_id == tid)
            db.execute(delete(TaskStep).where(TaskStep.run_id.in_(runs)))
            db.execute(delete(ScheduleOccurrence).where(ScheduleOccurrence.task_id == tid))
            db.execute(delete(TaskSchedule).where(TaskSchedule.task_id == tid))
            db.execute(delete(TaskRun).where(TaskRun.task_id == tid))
            db.execute(delete(TaskRevision).where(TaskRevision.task_id == tid))
            db.execute(delete(Task).where(Task.id == tid))
            db.commit()
