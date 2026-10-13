"""Connection revisions and catalog drift against a disposable PostgreSQL DB."""

import concurrent.futures
import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import ToolConnection, ToolConnectionCheck, ToolConnectionRevision
from sqlalchemy import delete, func, select


@pytest.mark.skipif(
    not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PostgreSQL CI DB required"
)
def test_connection_cas_and_probe_drift_postgres(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Refusing any database except loopback hub_ci")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    app = create_app(
        Settings(
            database_url=url,
            origin="http://testserver",
            secure_cookie=False,
            password_hash=password_hash("synthetic-mcp-pg-password"),
        )
    )
    factory = app.state.sessions
    item = None
    with TestClient(app) as client:
        login = client.post(
            "/api/login",
            headers={"Origin": "http://testserver"},
            json={"password": "synthetic-mcp-pg-password"},
        )
        headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf"]}
        body = {"name": "Synthetic PG MCP", "url": "https://example.org/mcp"}
        item = client.post("/api/connections", headers=headers, json=body).json()
        path = "/api/connections/" + item["id"]
        try:
            with concurrent.futures.ThreadPoolExecutor() as pool:
                futures = [
                    pool.submit(
                        client.put,
                        path,
                        headers=headers,
                        json={**body, "name": str(n), "expected_revision": 1},
                    )
                    for n in range(2)
                ]
                assert sorted(f.result(timeout=10).status_code for f in futures) == [200, 409]

            def changed(*args):
                with factory() as db:
                    row = db.get(ToolConnection, item["id"])
                    row.revision += 1
                    db.commit()
                return {"tools": [], "execution_allowed": False}

            monkeypatch.setattr("hub.connection_api.discover", changed)
            assert (
                client.post(
                    path + "/check", headers=headers, json={"expected_revision": 2}
                ).status_code
                == 409
            )
            with factory() as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(ToolConnectionCheck)
                        .where(ToolConnectionCheck.connection_id == item["id"])
                    )
                    == 0
                )
                assert (
                    len(
                        list(
                            db.scalars(
                                select(ToolConnectionRevision).where(
                                    ToolConnectionRevision.connection_id == item["id"]
                                )
                            )
                        )
                    )
                    == 2
                )
        finally:
            with factory() as db:
                for model in (ToolConnectionCheck, ToolConnectionRevision):
                    db.execute(delete(model).where(model.connection_id == item["id"]))
                db.execute(delete(ToolConnection).where(ToolConnection.id == item["id"]))
                db.commit()
