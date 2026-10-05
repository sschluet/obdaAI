"""Skill editing must not wait for a long-running unrelated Vault reconcile."""

import concurrent.futures
import json
import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import Skill, SkillRevision, session_factory
from sqlalchemy import delete, text


@pytest.mark.skipif(
    not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PostgreSQL CI DB required"
)
def test_skill_creation_independent_of_vault_reconcile_lock(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Refusing any database except loopback hub_ci")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    factory = session_factory(url)
    app = create_app(
        Settings(
            database_url=url,
            origin="http://testserver",
            secure_cookie=False,
            password_hash=password_hash("synthetic-skill-pg-password"),
        )
    )
    skill_id = None
    with TestClient(app) as c, factory() as vault:
        login = c.post(
            "/api/login",
            headers={"Origin": "http://testserver"},
            json={"password": "synthetic-skill-pg-password"},
        )
        headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf"]}
        vault.execute(text("SELECT pg_advisory_xact_lock(791103043)"))
        document = (
            "---\n"
            + json.dumps({"format": "obdaai-skill-1", "name": "Synthetic PG isolation"})
            + "\n---\nAnswer briefly."
        )
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                c.post, "/api/skills", headers=headers, json={"document": document}
            )
            try:
                result = future.result(timeout=3)
                assert result.status_code == 200
                skill_id = result.json()["id"]
            finally:
                vault.rollback()
                # Release the fixture lock even on failure before joining the thread.
                result = future.result(timeout=10)
                if result.status_code == 200:
                    skill_id = result.json()["id"]
                if skill_id:
                    with factory() as db:
                        db.execute(delete(SkillRevision).where(SkillRevision.skill_id == skill_id))
                        db.execute(delete(Skill).where(Skill.id == skill_id))
                        db.commit()
