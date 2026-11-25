import json
import os
import time
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
import test_chat
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hub.auth import require_session
from hub.db import ProviderConfig, ProviderTest, SchedulerPulse
from hub.runtime_status import install_runtime_status, runtime_status, worker_observation
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def seed(app, *, revision=1):
    with app.state.sessions() as db:
        db.add(ProviderConfig(
            id="synthetic-local", name="PRIVATE_PROVIDER_NAME", kind="local", revision=revision,
            enabled=True, is_default=True,
            config=json.dumps({"base_url": "http://PRIVATE_ADDRESS:1234", "model": "PRIVATE_MODEL",
                               "timeout": 42}), encrypted_secret="PRIVATE_ENCRYPTED_SECRET",
        ))
        db.commit()


def test_status_requires_auth_and_never_calls_models_or_writes(setup):
    app, client, _, provider = setup
    seed(app)
    with app.state.sessions() as db:
        before = db.scalar(select(func.count()).select_from(ProviderTest))
    response = client.get("/api/runtime-status")
    assert response.status_code == 200
    data = response.json()
    assert data["liveness"] == {"status": "ok"}
    assert data["database"] == {"status": "ok"}
    assert data["worker"]["status"] == "not_applicable"
    assert data["local"]["configured"] is True
    assert data["local"]["planner_readiness"] == "unknown"
    assert data["local"]["providers"][0]["last_model_probe"] is None
    assert data["local"]["providers"][0]["idle_seconds"] == 42
    assert data["timeouts"] == {
        "first_token_seconds": 120, "idle_seconds": 30, "queue_seconds": 120,
    }
    assert data["intent_interpretation"]["degraded"] is None
    assert "PRIVATE_" not in response.text
    assert provider.calls == 0 and provider.stream_calls == []
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ProviderTest)) == before
    client.cookies.clear()
    assert client.get("/api/runtime-status").status_code == 401
    assert client.get("/api/health").json()["status"] == "ok"


def test_probe_modes_revision_and_failure_are_not_conflated(setup):
    app, client, _, _ = setup
    seed(app, revision=2)
    with app.state.sessions() as db:
        db.add_all([
            ProviderTest(id="old-planner", provider_id="synthetic-local", revision=1,
                         mode="planner", status="succeeded", created=100, result="PRIVATE_RESULT"),
            ProviderTest(id="new-model", provider_id="synthetic-local", revision=2,
                         mode="model", status="succeeded", created=200, result="PRIVATE_RESULT"),
        ])
        db.commit()
    row = client.get("/api/runtime-status").json()["local"]["providers"][0]
    assert row["last_model_probe"]["mode"] == "model"
    assert row["last_model_probe"]["current_revision"] is True
    assert row["last_planner_probe"]["current_revision"] is False
    assert row["planner_readiness"] == "unknown"
    with app.state.sessions() as db:
        db.add(ProviderTest(id="current-planner", provider_id="synthetic-local", revision=2,
                            mode="planner", status="succeeded", created=time.time()))
        db.commit()
    row = client.get("/api/runtime-status").json()["local"]["providers"][0]
    assert row["planner_readiness"] == "last_probe_succeeded"
    assert row["last_planner_probe"]["evidence"] == "last_known_probe_not_current_readiness"
    with app.state.sessions() as db:
        current = db.get(ProviderTest, "current-planner")
        current.status = "failed"
        db.commit()
    assert client.get("/api/runtime-status").json()["local"]["providers"][0][
        "planner_readiness"
    ] == "unknown"


def test_intent_degradation_and_scheduler_are_separate_observations(setup, tmp_path):
    app, client, _, _ = setup
    app.state.intent_interpretation_degraded = True
    token = tmp_path / "scheduler-token"
    token.write_text("x" * 40)
    token.chmod(0o600)
    cfg = replace(app.state.settings, scheduler_enabled=True, scheduler_token_file=str(token))
    with app.state.sessions() as db:
        db.add(SchedulerPulse(id=1, last_tick=time.time()))
        db.commit()
    result = runtime_status(app, cfg, app.state.sessions)
    assert result["scheduler"]["healthy"] is True
    assert result["worker"]["status"] == "not_applicable"
    assert result["intent_interpretation"]["degraded"] is True
    app.state.intent_interpretation_degraded = False
    assert client.get("/api/runtime-status").json()["intent_interpretation"]["degraded"] is False


@pytest.mark.parametrize("timestamp,status", [(None, "unknown"), (990, "observed"),
                                               (900, "stale"), (1100, "stale")])
def test_postgres_worker_heartbeat_classification(timestamp, status):
    factory = MagicMock()
    query = factory.return_value.__enter__.return_value.execute.return_value
    query.scalar_one_or_none.return_value = timestamp
    assert worker_observation(factory, sqlite=False, now=1000)["status"] == status


def test_metadata_database_failure_is_sanitized_and_liveness_remains_separate(setup):
    original, _, _, _ = setup
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    factory = MagicMock(side_effect=OperationalError("PRIVATE_SQL", {}, Exception("PRIVATE_ERROR")))
    install_runtime_status(app, original.state.settings, factory)
    with TestClient(app) as client:
        response = client.get("/api/runtime-status")
    assert response.status_code == 200
    assert response.json()["database"]["status"] == "unavailable"
    assert response.json()["liveness"]["status"] == "ok"
    assert response.json()["local"]["planner_readiness"] == "unknown"
    assert "PRIVATE_" not in response.text


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG fixture required")
def test_worker_heartbeat_uses_real_postgres_timestamp_query(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only loopback hub_ci is allowed")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                # Exercise the real queue schema, without committing a worker or advancing its ID.
                connection.execute(text(
                    "INSERT INTO hub_queue.procrastinate_workers (id, last_heartbeat) "
                    "OVERRIDING SYSTEM VALUE VALUES (:worker_id, NOW())"
                ), {"worker_id": -time.time_ns()})
                factory = sessionmaker(bind=connection)
                observed = worker_observation(factory, sqlite=False, now=time.time())
                assert observed["status"] == "observed"
                assert observed["scope"] == "worker_processes_not_individual_queues"
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
