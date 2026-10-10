"""Real PostgreSQL foreign keys and permanent deletion in a disposable schema."""

import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from hub import db as models
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.deletion import DeletionInput, permanently_delete, preview
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema
from test_deletion import populate


@pytest.fixture
def pg_context(tmp_path):
    url = os.getenv("HUB_CI_DATABASE_URL")
    if not url:
        pytest.skip("Disposable loopback PostgreSQL required")
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci is allowed")
    admin = create_engine(url)
    schema = "deletion_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(CreateSchema(schema))
    engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
    try:
        models.Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        cfg = Settings(
            database_url=parsed.update_query_dict(
                {"options": "-csearch_path=" + schema + " -cstatement_timeout=3000"}
            ).render_as_string(hide_password=False),
            origin="http://testserver",
            secure_cookie=False,
            password_hash=password_hash("synthetic-password"),
            source_dir=str(tmp_path / "sources"),
            artifact_request_dir=str(tmp_path / "requests"),
            artifact_result_dir=str(tmp_path / "results"),
        )
        with factory() as db:
            db.add(models.AccountCredential(id=1, revision=0))
            db.add(models.LoginThrottle(id=1, window=0, attempts=0))
            db.commit()
        yield factory, cfg
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def test_actual_postgres_project_cascade(pg_context):
    factory, cfg = pg_context
    ids = populate(factory, cfg)
    with factory() as db:
        state = preview(db, "project", ids["project"], cfg)
    with factory() as db:
        result = permanently_delete(
            db,
            cfg,
            "project",
            ids["project"],
            DeletionInput(expected_state=state["expected_state"]),
        )
        assert result["deleted_conversation_ids"] == [ids["chat"]]
        assert db.get(models.Project, ids["project"]) is None
        assert db.get(models.Project, ids["other"])
        assert db.get(models.BudgetReservation, ids["run"])


def test_actual_postgres_chat_delete_keeps_financial_ledger(pg_context):
    factory, cfg = pg_context
    ids = populate(factory, cfg)
    with factory() as db:
        permanently_delete(db, cfg, "conversation", ids["chat"], None)
        assert db.get(models.Conversation, ids["chat"]) is None
        assert db.get(models.Project, ids["project"])
        assert db.get(models.Source, ids["source"])
        assert db.get(models.BudgetReservation, ids["run"])


def test_actual_postgres_ownership_lock_prevents_scope_race(pg_context):
    from hub.db_locks import OWNERSHIP, ownership_lock
    from sqlalchemy import text

    factory, cfg = pg_context
    ids = populate(factory, cfg)
    with factory() as deleting, factory() as competing:
        ownership_lock(deleting)
        acquired = competing.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": OWNERSHIP}
        )
        assert acquired is False
        competing.rollback()
        permanently_delete(deleting, cfg, "project", ids["project"], None)
        ownership_lock(competing)
        assert competing.get(models.Project, ids["project"]) is None


def test_actual_postgres_source_event_detach_preserves_history(pg_context):
    from test_deletion import test_completed_source_event_history_detaches_with_snapshot

    test_completed_source_event_history_detaches_with_snapshot(pg_context)


def test_actual_postgres_vault_scan_does_not_lock_login_chat_or_unscoped_delete(pg_context):
    from hub.db_locks import MEMORY_INDEX, OWNERSHIP
    from hub.memory import serialize
    from sqlalchemy import text

    factory, cfg = pg_context
    ids = populate(factory, cfg)
    with factory() as db:
        db.add(
            models.Memory(
                path="bound.md",
                project_id=ids["other"],
                sha256="a" * 64,
                content="historical",
                deleted=True,
            )
        )
        db.commit()
    with factory() as scanning:
        serialize(scanning)
        scanning.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MEMORY_INDEX})
        with factory() as checking:
            assert (
                checking.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": OWNERSHIP})
                is True
            )
        with TestClient(create_app(cfg)) as client:
            login = client.post(
                "/api/login",
                json={"password": "synthetic-password"},
                headers={"Origin": cfg.origin},
            )
            assert login.status_code == 200, login.text
            headers = {"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]}
            chat = client.post("/api/conversations", json={}, headers=headers)
            assert chat.status_code == 200, chat.text
            assert client.post("/api/logout", headers=headers).status_code == 200
        with factory() as deleting:
            permanently_delete(deleting, cfg, "project", ids["project"], None)
        with factory() as scoped:
            with pytest.raises(HTTPException) as error:
                permanently_delete(scoped, cfg, "project", ids["other"], None)
            assert error.value.status_code == 409 and "Vault-Abgleich" in error.value.detail
