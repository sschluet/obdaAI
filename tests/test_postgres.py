"""Optional test against a disposable CI database, never a production DB."""

import asyncio
import json
import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import Conversation, Message, Run, RunEvent, session_factory
from hub.jobs import enqueue, requeue_stalled, worker_app
from hub.routing import Route
from hub.titles import reserve_title
from sqlalchemy import create_engine, inspect, select, text, update
from test_chat import FakeProviders


@pytest.mark.skipif(
    not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PostgreSQL CI DB not available"
)
def test_postgres_migration_and_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Refusing to migrate any database except a loopback hub_ci fixture")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    assert "conversations" in inspect(engine).get_table_names()
    app = create_app(
        Settings(
            database_url=url,
            origin="http://testserver",
            secure_cookie=False,
            password_hash=password_hash("synthetic-postgres-password"),
        )
    )
    with TestClient(app) as client:
        login = client.post(
            "/api/login",
            json={"password": "synthetic-postgres-password"},
            headers={"Origin": "http://testserver"},
        )
        assert login.status_code == 200
        headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf"]}
        result = client.post("/api/conversations", json={}, headers=headers)
        assert result.status_code == 200
        assert client.get("/api/conversations/" + result.json()["id"]).status_code == 200
    # Real upstream schema, transaction deferral and worker; no model network.
    factory = session_factory(url)
    settings = app.state.settings
    chat_id = result.json()["id"]
    with factory() as db:
        rejected = Run(conversation_id=chat_id, status="queued")
        db.add(rejected)
        db.flush()
        enqueue(db, settings, rejected.id)
        db.rollback()
        assert db.scalar(text("SELECT count(*) FROM hub_queue.procrastinate_jobs")) == 0
    with factory() as db:
        reserve_title(db, settings, chat_id)
        assert db.scalar(text("SELECT count(*) FROM hub_queue.procrastinate_jobs")) == 1
        db.rollback()
        assert db.scalar(text("SELECT count(*) FROM hub_queue.procrastinate_jobs")) == 0
        assert db.get(Conversation, chat_id).title_status == "idle"
    with factory() as db:
        run = Run(conversation_id=chat_id, status="queued")
        db.add(run)
        db.add(Message(conversation_id=chat_id, role="user", content="synthetic queue fixture"))
        db.flush()
        enqueue(db, settings, run.id)
        db.commit()
        run_id = run.id
        assert db.scalar(text("SELECT count(*) FROM hub_queue.procrastinate_jobs")) == 1
    # API restart must leave durable pending work intact.
    with TestClient(create_app(settings)):
        with factory() as db:
            assert db.get(Run, run_id).status == "queued"
    import hub.jobs as jobs

    fake = FakeProviders(
        Route(
            capabilities=["chat"],
            model_class="local",
            reason="queue fixture",
            answer="SYNTHETIC_QUEUE_REPLY",
        )
    )
    monkeypatch.setattr(jobs, "Providers", lambda cfg: fake)
    queue = worker_app(settings)

    async def drain():
        async with queue.open_async():
            await queue.run_worker_async(
                queues=["chat", "titles"], wait=False, install_signal_handlers=False, concurrency=1
            )

    asyncio.run(drain())
    assert fake.calls == 1
    with factory() as db:
        assert db.get(Conversation, chat_id).title == "Synthetic conversation"
        assert db.get(Run, run_id).status == "succeeded"
        events = db.scalars(select(RunEvent).where(RunEvent.run_id == run_id)).all()
        assert any(json.loads(e.payload).get("text") == "SYNTHETIC_QUEUE_REPLY" for e in events)
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM hub_queue.procrastinate_jobs "
                    "WHERE task_name IN ('hub.chat','hub.title') AND status::text <> 'succeeded'"
                )
            )
            == 0
        )
    # A stalled task redispatch reconciles output without a second model call.
    with factory() as db:
        stale = Run(
            conversation_id=chat_id,
            status="streaming",
            provider="openrouter",
            model="synthetic/crashed-answer-model",
            answer_model_used=True,
        )
        db.add(stale)
        db.flush()
        db.add(
            RunEvent(
                run_id=stale.id,
                sequence=1,
                kind="delta",
                payload=json.dumps({"text": "SYNTHETIC_CRASH_PARTIAL"}),
            )
        )
        enqueue(db, settings, stale.id)
        db.commit()
        stale_id = stale.id
        db.execute(text("SET LOCAL search_path TO hub_queue, public"))
        db.execute(
            text(
                "UPDATE hub_queue.procrastinate_jobs SET status='doing' WHERE args->>'run_id'=:run"
            ),
            {"run": stale_id},
        )
        db.commit()

    async def recover():
        async with queue.open_async():
            await requeue_stalled(queue)

    asyncio.run(recover())
    asyncio.run(drain())
    assert fake.calls == 1
    with factory() as db:
        assert db.get(Run, stale_id).status == "interrupted"
        partial = db.scalar(select(Message).where(Message.content == "SYNTHETIC_CRASH_PARTIAL"))
        assert partial is not None and partial.label == "LOCAL_ONLY"
        assert partial.run_id == stale_id
        recovered = db.get(Run, partial.run_id)
        assert recovered.provider == "openrouter"
        assert recovered.model == "synthetic/crashed-answer-model"
        assert recovered.answer_model_used is True
    with factory() as db:
        db.add(Message(conversation_id=chat_id, role="user", content="Häuser wurden gebaut"))
        db.add(
            Message(
                conversation_id=chat_id,
                role="user",
                content="archivierter Geheimbegriff",
                active=False,
            )
        )
        db.commit()
    with TestClient(create_app(settings)) as client:
        r = client.post(
            "/api/login",
            json={"password": "synthetic-postgres-password"},
            headers={"Origin": "http://testserver"},
        )
        assert r.status_code == 200
        assert client.get("/api/conversations?q=Haus").json()[0]["id"] == chat_id
        assert client.get("/api/conversations?q=Geheimbegriff").json() == []
    # Real PostgreSQL serialization prevents overlapping API/worker Vault scans
    # from importing the same canonical note twice before either commits.
    # Scoped ownership now precedes the memory index lock, so a competing scan
    # can wait at either protected boundary.
    import concurrent.futures
    import tempfile
    import time
    from pathlib import Path

    from hub.db import Memory
    from hub.memory import reconcile

    with tempfile.TemporaryDirectory() as directory:
        vault = Path(directory)
        (vault / "AI/Memory").mkdir(parents=True)
        (vault / "synthetic.md").write_text("SYNTHETIC SERIALIZED VAULT")

        def second_scan():
            with factory() as db:
                result = reconcile(db, vault, allow_memory_writes=True)
                db.commit()
                return result

        with factory() as first, concurrent.futures.ThreadPoolExecutor() as pool:
            assert reconcile(first, vault, allow_memory_writes=True)["files"] == 1
            future = pool.submit(second_scan)
            try:
                waiting = False
                for _ in range(100):
                    with engine.connect() as probe:
                        waiting = bool(
                            probe.scalar(
                                text(
                                    "SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
                                    "AND objid IN (791103043, 791103049) AND NOT granted"
                                )
                            )
                        )
                    if waiting:
                        break
                    time.sleep(0.01)
                assert waiting and not future.done()
                first.commit()
                assert future.result(timeout=5)["files"] == 1
            finally:
                first.rollback()  # Also releases the lock on a failed assertion.
            with factory() as db:
                imported = list(db.scalars(select(Memory).where(Memory.path == "synthetic.md")))
                assert len(imported) == 1 and not imported[0].deleted
    with pytest.raises(RuntimeError, match="Preserve message processing provenance"):
        command.downgrade(cfg, "base")
    # This guarded loopback hub_ci database is disposable. Explicitly remove
    # this test's scratch provenance before exercising a destructive reset.
    # Production must retain it and the downgrade guard remains unchanged.
    with factory() as db:
        db.execute(update(Message).where(Message.conversation_id == chat_id).values(run_id=None))
        db.execute(update(Run).where(Run.conversation_id == chat_id).values(answer_model_used=None))
        db.commit()
    engine.dispose()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PostgreSQL required")
def test_postgres_action_concurrent_receipt_and_pause(monkeypatch):
    import concurrent.futures
    import uuid

    from hub.db import ActionGrant, ActionIntent, ActionReceipt, Project
    from sqlalchemy import delete, func

    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Refusing any database except loopback hub_ci")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    settings = Settings(
        database_url=url,
        origin="http://testserver",
        secure_cookie=False,
        password_hash=password_hash("synthetic-gateway-password"),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        login = client.post(
            "/api/login",
            json={"password": "synthetic-gateway-password"},
            headers={"Origin": settings.origin},
        )
        headers = {"Origin": settings.origin, "X-CSRF-Token": login.json()["csrf"]}
        policy = client.get("/api/action-policy").json()
        client.patch(
            "/api/action-policy",
            json={"paused": False, "expected_revision": policy["revision"]},
            headers=headers,
        )
        project = client.post(
            "/api/projects", json={"name": "Synthetic concurrent gateway"}, headers=headers
        ).json()
        action = client.post(
            "/api/actions",
            json={
                "request_id": str(uuid.uuid4()),
                "tool_id": "project.archive",
                "parameters": {
                    "project_id": project["id"],
                    "expected_revision": project["revision"],
                },
            },
            headers=headers,
        ).json()
        assert (
            client.post(
                "/api/actions/" + action["id"] + "/grant",
                json={"parameters_sha256": action["parameters_sha256"], "tool_revision": 1},
                headers=headers,
            ).status_code
            == 200
        )

        def execute(_):
            return client.post(
                "/api/actions/" + action["id"] + "/execute", json={}, headers=headers
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(execute, range(2)))
        assert all(r.status_code == 200 for r in responses)
        assert responses[0].json()["receipt"] == responses[1].json()["receipt"]
        with app.state.sessions() as db:
            saved = db.get(Project, project["id"])
            assert saved.archived and saved.revision == project["revision"] + 1
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ActionReceipt)
                    .where(ActionReceipt.action_id == action["id"])
                )
                == 1
            )
        policy = client.get("/api/action-policy").json()
        assert (
            client.patch(
                "/api/action-policy",
                json={"paused": True, "expected_revision": policy["revision"]},
                headers=headers,
            ).status_code
            == 200
        )
        assert execute(None).status_code == 200
        # Only this disposable test's audit is removed; production downgrade preserves audit.
        with app.state.sessions() as db:
            db.execute(delete(ActionReceipt).where(ActionReceipt.action_id == action["id"]))
            db.execute(delete(ActionGrant).where(ActionGrant.action_id == action["id"]))
            db.execute(delete(ActionIntent).where(ActionIntent.id == action["id"]))
            db.commit()
