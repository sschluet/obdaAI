"""Real PostgreSQL callback serialization and atomic queue linkage, CI database only."""

import base64
import concurrent.futures
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.action_api import digest, encode
from hub.api import create_app
from hub.config import Settings
from hub.db import Task, TaskRevision, TaskRun, WorkflowBinding, WorkflowDispatch
from hub.n8n_workflows import task_workflow
from hub.provider_settings import encrypt
from hub.task_api import TaskSpec
from sqlalchemy import delete, func, select, text


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG fixture required")
def test_duplicate_callbacks_commit_one_run_and_queue_job(tmp_path, monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only loopback hub_ci is allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    key = tmp_path / "master.key"
    key.write_text(base64.b64encode(os.urandom(32)).decode())
    key.chmod(0o600)
    cfg = Settings(database_url=url, secrets_key_file=str(key))
    app = create_app(cfg)
    bid, did = str(uuid.uuid4()), str(uuid.uuid4())
    version = str(uuid.uuid4())
    with app.state.sessions() as db:
        task = Task(paused=False)
        db.add(task)
        db.flush()
        document = encode(
            TaskSpec(title="Synthetic PG callback", goal="Count").model_dump(mode="json")
        )
        db.add(TaskRevision(task_id=task.id, revision=1, spec=document, sha256=digest(document)))
        graph = task_workflow(bid, task.id, 1, "fixed-header", "fixed-ca")
        remote = {
            **graph,
            "id": "fixed-workflow",
            "versionId": version,
            "active": True,
            "activeVersionId": version,
        }
        monkeypatch.setattr("hub.workflow_api.remote", lambda *a, **kw: remote)
        db.add(
            WorkflowBinding(
                id=bid,
                task_id=task.id,
                task_revision=1,
                control_revision=1,
                spec_sha256=digest(document),
                status="ready",
                graph=encode(graph),
                remote_id="fixed-workflow",
                remote_version=version,
                encrypted_secret=encrypt(cfg, "workflow:" + bid, "synthetic-callback"),
            )
        )
        db.flush()
        db.add(WorkflowDispatch(id=did, binding_id=bid, control_revision=1))
        db.commit()
        tid = task.id
    try:
        with TestClient(app) as c:

            def callback():
                r = c.post(
                    "/api/workflow-callback/" + bid,
                    headers={"X-OBDAAI-WORKFLOW": "synthetic-callback"},
                    json={"dispatch_id": did, "execution_id": "501"},
                )
                assert r.status_code == 200, r.text
                return r.json()

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: callback(), range(2)))
            assert results[0] == results[1]
        with app.state.sessions() as db:
            dispatch = db.get(WorkflowDispatch, did)
            assert dispatch.status == "accepted" and dispatch.run_id == results[0]["run_id"]
            assert (
                db.scalar(select(func.count()).select_from(TaskRun).where(TaskRun.task_id == tid))
                == 1
            )
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM hub_queue.procrastinate_jobs "
                        "WHERE task_name='hub.task-read' AND args->>'run_id'=:rid"
                    ),
                    {"rid": dispatch.run_id},
                )
                == 1
            )
    finally:
        with app.state.sessions() as db:
            # Queue delete triggers resolve their schema-local helper relations.
            db.execute(text("SET LOCAL search_path TO hub_queue, public"))
            db.execute(
                text(
                    "DELETE FROM hub_queue.procrastinate_jobs WHERE args->>'run_id' "
                    "IN (SELECT id FROM task_runs WHERE task_id=:tid)"
                ),
                {"tid": tid},
            )
            db.execute(delete(WorkflowDispatch).where(WorkflowDispatch.binding_id == bid))
            db.execute(delete(WorkflowBinding).where(WorkflowBinding.id == bid))
            db.execute(delete(TaskRun).where(TaskRun.task_id == tid))
            db.execute(delete(TaskRevision).where(TaskRevision.task_id == tid))
            db.execute(delete(Task).where(Task.id == tid))
            db.commit()
