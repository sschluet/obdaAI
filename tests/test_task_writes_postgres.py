"""Disposable PostgreSQL: duplicate delivery produces one effect and gateway receipt."""

import asyncio
import os
import time
import uuid

import pytest
from alembic import command
from alembic.config import Config
from hub.action_api import digest, encode
from hub.config import Settings
from hub.db import (
    ActionGrant,
    ActionIntent,
    ActionPolicy,
    ActionReceipt,
    Project,
    Task,
    TaskActionLink,
    TaskRevision,
    TaskRun,
    TaskStep,
    TaskWriteGrant,
    TaskWriteGrantEvent,
    session_factory,
)
from hub.jobs import enqueue_task_read, worker_app
from hub.task_api import TaskSpec, check_bindings
from hub.task_writes import prepare_run
from sqlalchemy import delete, func, select


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG fixture required")
def test_bounded_write_duplicate_pg_queue_delivery(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only loopback hub_ci is allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    cfg = Settings(database_url=url)
    factory = session_factory(url)
    with factory() as db:
        policy = db.get(ActionPolicy, 1)
        before = policy.paused, policy.revision
        policy.paused, policy.revision = False, policy.revision + 1
        project, task = Project(name="Synthetic PG task write"), Task(paused=False)
        db.add_all([project, task])
        db.flush()
        spec = TaskSpec.model_validate(
            {
                "title": "Synthetic bounded archive",
                "goal": "One reversible local change",
                "autonomy": "bounded_autonomous",
                "success_criterion": "all_steps_completed",
                "steps": [
                    {
                        "tool_id": "project.archive",
                        "parameters": {
                            "project_id": project.id,
                            "expected_revision": project.revision,
                        },
                    }
                ],
            }
        )
        document = encode(spec.model_dump(mode="json"))
        db.add(TaskRevision(task_id=task.id, revision=1, spec=document, sha256=digest(document)))
        db.add(
            TaskWriteGrant(
                task_id=task.id,
                task_revision=1,
                control_revision=1,
                spec_sha256=digest(document),
                policy_revision=policy.revision,
                expires=time.time() + 300,
            )
        )
        db.commit()
        pid, tid = project.id, task.id
    rid = None
    try:
        with factory() as db:
            run = TaskRun(
                task_id=tid,
                task_revision=1,
                control_revision=1,
                request_key=str(uuid.uuid4()),
                request_digest=digest("synthetic"),
                snapshot=encode(check_bindings(db, spec)),
            )
            db.add(run)
            db.flush()
            prepare_run(db, run, spec)
            rid = run.id
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
            assert db.get(Project, pid).archived and db.get(Project, pid).revision == 2
            assert db.get(TaskWriteGrant, tid).used
            assert (
                db.scalar(select(func.count()).select_from(TaskStep).where(TaskStep.run_id == rid))
                == 1
            )
            links = list(db.scalars(select(TaskActionLink).where(TaskActionLink.run_id == rid)))
            assert len(links) == 1 and db.get(ActionReceipt, links[0].action_id)
    finally:
        with factory() as db:
            ids = list(
                db.scalars(select(TaskActionLink.action_id).where(TaskActionLink.run_id == rid))
            )
            db.execute(delete(TaskActionLink).where(TaskActionLink.run_id == rid))
            for model in (ActionReceipt, ActionGrant):
                db.execute(delete(model).where(model.action_id.in_(ids)))
            db.execute(delete(ActionIntent).where(ActionIntent.id.in_(ids)))
            db.execute(delete(TaskStep).where(TaskStep.run_id == rid))
            db.execute(delete(TaskRun).where(TaskRun.task_id == tid))
            db.execute(delete(TaskWriteGrantEvent).where(TaskWriteGrantEvent.task_id == tid))
            db.execute(delete(TaskWriteGrant).where(TaskWriteGrant.task_id == tid))
            db.execute(delete(TaskRevision).where(TaskRevision.task_id == tid))
            db.execute(delete(Task).where(Task.id == tid))
            db.execute(delete(Project).where(Project.id == pid))
            policy = db.get(ActionPolicy, 1)
            policy.paused, policy.revision = before
            db.commit()
