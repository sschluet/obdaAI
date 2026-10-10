"""Real PostgreSQL foreign keys and permanent deletion in a disposable schema."""

import os
from uuid import uuid4

import pytest
from hub import db as models
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
            database_url=url,
            source_dir=str(tmp_path / "sources"),
            artifact_request_dir=str(tmp_path / "requests"),
            artifact_result_dir=str(tmp_path / "results"),
        )
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
