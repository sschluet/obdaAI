import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from hub.db import session_factory
from hub.task_model import execution_lock
from sqlalchemy import text


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PostgreSQL required")
def test_session_inference_lock_survives_commit_and_keeps_control_independent(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only loopback disposable hub_ci allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    factory = session_factory(url)
    rid = str(uuid.uuid4())
    with execution_lock(factory, rid) as first:
        assert first
        with execution_lock(factory, rid) as duplicate:
            assert not duplicate
        with factory() as db:
            assert db.scalar(text("SELECT pg_try_advisory_xact_lock(791103045)"))
            db.rollback()
    with execution_lock(factory, rid) as recovered:
        assert recovered
