"""Actual queue transaction and worker, loopback disposable CI database only."""

import asyncio
import json
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from hub.action_api import digest, encode
from hub.config import Settings
from hub.db import Task, TaskRevision, TaskRun, TaskStep, session_factory
from hub.jobs import enqueue_task_read, worker_app
from hub.task_api import TaskSpec
from sqlalchemy import delete, func, select, text


@pytest.mark.skipif(
    not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG queue fixture required"
)
def test_task_queue_commits_atomically_and_duplicate_worker_has_one_receipt(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only loopback hub_ci is allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    cfg = Settings(database_url=url)
    factory = session_factory(url)
    with factory() as db:
        t = Task(paused=False)
        db.add(t)
        db.flush()
        document = encode(
            TaskSpec(title="Synthetic PG task", goal="Count resources").model_dump(mode="json")
        )
        db.add(TaskRevision(task_id=t.id, revision=1, spec=document, sha256=digest(document)))
        db.commit()
        tid = t.id
    rid = None
    try:
        with factory() as db:
            rejected = TaskRun(
                task_id=tid,
                task_revision=1,
                control_revision=1,
                request_key=str(uuid.uuid4()),
                request_digest=digest("synthetic rollback"),
                snapshot=encode(
                    {
                        "spec": json.loads(document),
                        "skills_checked": [],
                        "model": None,
                        "cost_usd": 0,
                        "label": "LOCAL_ONLY",
                    }
                ),
            )
            db.add(rejected)
            db.flush()
            enqueue_task_read(db, cfg, rejected.id)
            db.rollback()
            assert not db.scalar(
                text(
                    "SELECT count(*) FROM hub_queue.procrastinate_jobs "
                    "WHERE task_name='hub.task-read'"
                )
            )
            r = TaskRun(
                task_id=tid,
                task_revision=1,
                control_revision=1,
                request_key=str(uuid.uuid4()),
                request_digest=digest("synthetic commit"),
                snapshot=encode(
                    {
                        "spec": json.loads(document),
                        "skills_checked": [],
                        "model": None,
                        "cost_usd": 0,
                        "label": "LOCAL_ONLY",
                    }
                ),
            )
            db.add(r)
            db.flush()
            rid = r.id
            enqueue_task_read(db, cfg, rid)
            enqueue_task_read(db, cfg, rid)
            db.commit()
        queue = worker_app(cfg)

        async def work():
            async with queue.open_async():
                await queue.run_worker_async(
                    queues=["tasks"], wait=False, install_signal_handlers=False, concurrency=2
                )

        asyncio.run(work())
        with factory() as db:
            assert db.get(TaskRun, rid).status == "succeeded"
            assert (
                db.scalar(select(func.count()).select_from(TaskStep).where(TaskStep.run_id == rid))
                == 1
            )
    finally:
        with factory() as db:
            if rid:
                db.execute(delete(TaskStep).where(TaskStep.run_id == rid))
            db.execute(delete(TaskRun).where(TaskRun.task_id == tid))
            db.execute(delete(TaskRevision).where(TaskRevision.task_id == tid))
            db.execute(delete(Task).where(Task.id == tid))
            db.commit()
