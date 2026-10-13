"""Actual CAS concurrency in the explicit disposable loopback CI PG database only."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import Conversation, ResponsePreference, ResponsePreferenceRevision
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url


@pytest.mark.skipif(
    not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PostgreSQL CI DB unavailable"
)
def test_preference_cas_serializes_concurrent_first_writes(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Refusing any database except loopback hub_ci fixture")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    app = create_app(
        Settings(
            database_url=url,
            origin="http://testserver",
            secure_cookie=False,
            password_hash=password_hash("synthetic-preferences-ci"),
        )
    )
    identifier = None
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/login",
                json={"password": "synthetic-preferences-ci"},
                headers={"Origin": "http://testserver"},
            )
            assert login.status_code == 200
            headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf"]}
            created = client.post("/api/conversations", json={}, headers=headers)
            assert created.status_code == 200
            identifier = created.json()["id"]
            path = "/api/preferences/conversations/" + identifier
            barrier = Barrier(2)

            def write(language):
                barrier.wait(timeout=5)
                return client.put(
                    path,
                    json={"expected_revision": 0, "overrides": {"language": language}},
                    headers=headers,
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(write, ["de", "en"]))
            assert sorted(response.status_code for response in responses) == [200, 409]
            state = client.get(path).json()
            assert state["revision"] == 1
            assert state["effective"]["language"] in ("de", "en")
            assert client.get("/api/conversations/" + identifier).json()["cloud_allowed"] is False
            with app.state.sessions() as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(ResponsePreferenceRevision)
                        .where(ResponsePreferenceRevision.key == "conversation:" + identifier)
                    )
                    == 1
                )
    finally:
        if identifier:
            with app.state.sessions() as db:
                key = "conversation:" + identifier
                db.execute(
                    delete(ResponsePreferenceRevision).where(ResponsePreferenceRevision.key == key)
                )
                db.execute(delete(ResponsePreference).where(ResponsePreference.key == key))
                db.execute(delete(Conversation).where(Conversation.id == identifier))
                db.commit()
