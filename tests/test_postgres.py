"""Optional test against a disposable CI database, never a production DB."""

import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from sqlalchemy import create_engine, inspect


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
    engine.dispose()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
