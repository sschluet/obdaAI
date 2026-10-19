"""Pinned, human-authenticated Bridge setup revokes old accounts before changes."""

import base64
import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hub import proton_bridge_setup as setup
from hub.agent_models import AgentPolicy
from hub.api import create_app
from hub.auth import password_hash, require_session
from hub.config import Settings
from hub.db import Base, session_factory
from hub.integrations import Integration
from hub.provider_settings import encrypt

URL = "/api/integrations/proton-bridge-setup"


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_text(base64.b64encode(b"s" * 32).decode())
    key.chmod(0o600)
    token = tmp_path / "token"
    token.write_text("synthetic-control-token")
    token.chmod(0o600)
    profile_id = str(uuid4())
    cfg = Settings(
        database_url="sqlite:///" + str(tmp_path / "bridge.sqlite"),
        secrets_key_file=str(key),
        integration_targets_enabled=True,
        proton_bridge_control_url="http://127.0.0.1:18765",
        proton_bridge_control_token_file=str(token),
        proton_bridge_integration_id=profile_id,
        proton_bridge_mcp_url="http://127.0.0.1:18764/mcp",
        mcp_endpoints_json=json.dumps({"http://127.0.0.1:18764/mcp": "127.0.0.1"}),
    )
    factory = session_factory(cfg.database_url)
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as db:
        db.add(
            Integration(
                id=profile_id,
                name="Proton Mail",
                kind="mcp",
                revision=1,
                enabled=True,
                writes_enabled=True,
                config=json.dumps(
                    {"url": cfg.proton_bridge_mcp_url, "auth": "bearer", "protocol": "2025-11-25"}
                ),
                encrypted_secret=encrypt(cfg, "integration:" + profile_id, "synthetic-mcp-token"),
            )
        )
        db.commit()
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    setup.install_proton_bridge_setup(app, cfg, factory)
    effects = []

    def control(cfg, body=None):
        if body is not None:
            with factory() as db:
                row = db.get(Integration, profile_id)
                assert not row.enabled and not row.writes_enabled and row.revision == 2
            effects.append(body)
        return {
            "revision": len(effects),
            "username": "mail@example.test" if effects else "",
            "connected": bool(effects),
        }

    monkeypatch.setattr(setup, "control", control)
    monkeypatch.setattr(
        setup,
        "mcp_catalog",
        lambda *args: {
            "label": "LOCAL_ONLY",
            "tools": [
                {"name": name, "input_schema": {"type": "object", "additionalProperties": False}}
                for name in setup.READ_TOOLS | {"export_emails", "send_email"}
            ],
        },
    )
    with TestClient(app) as client:
        yield client, factory, cfg, profile_id, effects


def payload(**changes):
    return {
        "name": "Proton",
        "username": "mail@example.test",
        "password": "synthetic-bridge-password",
        "expected_revision": 1,
        "request_id": str(uuid4()),
        "enable_reads": True,
        **changes,
    }


def test_default_disabled():
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    setup.install_proton_bridge_setup(app, Settings(), lambda: None)

    # No database is required by the default installation, but route context owns it.
    class Context:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return None

    app2 = FastAPI()
    app2.dependency_overrides[require_session] = lambda: None
    setup.install_proton_bridge_setup(app2, Settings(), Context)
    with TestClient(app2) as client:
        assert client.get(URL).json()["available"] is False
        assert client.post(URL, json=payload()).status_code == 503


def test_readonly_grants_secrets_and_idempotency(bridge):
    client, factory, cfg, profile_id, effects = bridge
    body = payload()
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["connected"] and response.json()["enable_reads"]
    assert body["password"] not in response.text
    assert client.post(URL, json=body).status_code == 200
    assert len(effects) == 1
    assert client.post(URL, json={**body, "password": "different"}).status_code == 409
    with factory() as db:
        row = db.get(Integration, profile_id)
        policy = db.get(AgentPolicy, profile_id)
        assert row.enabled and not row.writes_enabled and row.revision == 2
        assert body["password"] not in row.last_check + row.config + policy.rules
        rules = json.loads(policy.rules)
        assert set(rules["mcp_read_tools"]) == setup.READ_TOOLS
        assert not rules["mcp"] and not rules["autonomous"]
        assert not rules["private_data_to_target"] and rules["max_effects"] == 0
        assert policy.profile_revision == row.revision


def test_failure_keeps_old_jobs_revoked(bridge, monkeypatch):
    client, factory, cfg, profile_id, effects = bridge

    def fail(*args):
        raise ValueError("synthetic secret never returned")

    monkeypatch.setattr(setup, "control", fail)
    body = payload()
    assert client.post(URL, json=body).status_code == 502
    assert client.post(URL, json=body).status_code == 409
    with factory() as db:
        row = db.get(Integration, profile_id)
        assert not row.enabled and not row.writes_enabled and row.revision == 2
    assert not effects


def test_revision_and_fixed_target(bridge):
    client, factory, cfg, profile_id, effects = bridge
    assert client.post(URL, json=payload(expected_revision=5)).status_code == 409
    assert client.post(URL, json=payload(host="example.test")).status_code == 422
    with factory() as db:
        row = db.get(Integration, profile_id)
        row.config = json.dumps({"url": "http://127.0.0.1:18764/other"})
        db.commit()
    assert client.post(URL, json=payload()).status_code == 503
    assert not effects


def test_blank_preserves_password_and_disable_reads(bridge):
    client, factory, cfg, profile_id, effects = bridge
    result = client.post(URL, json=payload(password="", enable_reads=False))
    assert result.status_code == 200
    assert effects[0]["password"] is None
    assert not result.json()["enable_reads"]
    with factory() as db:
        assert not db.get(Integration, profile_id).enabled
        assert not json.loads(db.get(AgentPolicy, profile_id).rules)["mcp_read_tools"]


def test_missing_catalog_tools_never_enables(bridge, monkeypatch):
    client, factory, cfg, profile_id, effects = bridge
    monkeypatch.setattr(setup, "mcp_catalog", lambda *args: {"label": "LOCAL_ONLY", "tools": []})
    assert client.post(URL, json=payload()).status_code == 502
    with factory() as db:
        assert not db.get(Integration, profile_id).enabled


def test_real_auth_and_csrf(tmp_path, monkeypatch):
    cfg = Settings(
        database_url="sqlite:///" + str(tmp_path / "auth.sqlite"),
        origin="http://testserver",
        secure_cookie=False,
        password_hash=password_hash("synthetic-password"),
    )
    monkeypatch.setenv("HUB_DATABASE_URL", cfg.database_url)
    command.upgrade(Config("alembic.ini"), "head")
    with TestClient(create_app(cfg)) as client:
        assert client.get(URL).status_code == 401
        login = client.post(
            "/api/login", json={"password": "synthetic-password"}, headers={"Origin": cfg.origin}
        )
        assert login.status_code == 200, login.text
        assert client.post(URL, json=payload(), headers={"Origin": cfg.origin}).status_code == 403
        assert (
            client.post(
                URL,
                json=payload(),
                headers={"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]},
            ).status_code
            == 503
        )


@pytest.mark.parametrize(
    "changes",
    [{"expected_revision": "1"}, {"enable_reads": "yes"}, {"username": 42}, {"password": 42}],
)
def test_setup_rejects_coerced_authority(bridge, changes):
    client, factory, cfg, profile_id, effects = bridge
    assert client.post(URL, json=payload(**changes)).status_code == 422
    assert not effects


def test_catalog_readiness_retries_only_reads_while_profile_disabled(bridge, monkeypatch):
    from dataclasses import replace

    import httpx
    from hub.integration_transport import requests_plan

    client, factory, cfg, profile_id, effects = bridge
    cfg = replace(cfg, proton_bridge_mcp_url="http://proton.example.test:18764/mcp")
    with factory() as db:
        row = db.get(Integration, profile_id)
        config = json.loads(row.config)
        config["url"] = cfg.proton_bridge_mcp_url
        row.config = json.dumps(config)
        db.commit()
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    setup.install_proton_bridge_setup(app, cfg, factory)
    monkeypatch.setattr(
        "hub.integration_transport.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("192.168.20.10", 18764))],
    )
    original = setup.mcp_catalog
    probes = []
    sleeps = []
    monkeypatch.setattr(setup.time, "sleep", lambda value: sleeps.append(value))

    def catalog(*args):
        with factory() as db:
            row = db.get(Integration, profile_id)
            assert not row.enabled and not row.writes_enabled
            assert json.loads(row.last_check)["status"] == "pending"
            assert json.loads(row.last_check)["proton_setup"]["created"] > 0
        assert requests_plan(factory, cfg) == [
            {"id": profile_id, "kind": "mcp", "targets": [("192.168.20.10", 18764)]}
        ]
        assert len(effects) == 1  # Broker verified/stored credentials exactly once.
        probes.append("catalog-only")
        if len(probes) < 3:
            raise httpx.ConnectError("Synthetic observer rule not applied yet")
        return original(*args)

    monkeypatch.setattr(setup, "mcp_catalog", catalog)
    with TestClient(app) as c:
        response = c.post(URL, json=payload())
    assert response.status_code == 200, response.text
    assert len(probes) == 3 and sleeps == [1, 1] and len(effects) == 1
    with factory() as db:
        row = db.get(Integration, profile_id)
        assert row.enabled and not row.writes_enabled
        assert json.loads(row.last_check)["status"] == "succeeded"


def test_catalog_invalid_data_fails_immediately_without_broker_replay(bridge, monkeypatch):
    client, factory, cfg, profile_id, effects = bridge
    probes = []

    def invalid(*args):
        probes.append("catalog")
        raise ValueError("Synthetic authentication/catalog failure")

    monkeypatch.setattr(setup, "mcp_catalog", invalid)
    monkeypatch.setattr(
        setup.time, "sleep", lambda *a: pytest.fail("Invalid catalog must not be retried")
    )
    body = payload()
    assert client.post(URL, json=body).status_code == 502
    assert client.post(URL, json=body).status_code == 409
    assert probes == ["catalog"] and len(effects) == 1
    with factory() as db:
        assert not db.get(Integration, profile_id).enabled


def test_catalog_connection_deadline_keeps_disabled_without_repeating_broker(bridge, monkeypatch):
    import httpx

    client, factory, cfg, profile_id, effects = bridge

    def not_ready(*args):
        raise httpx.ConnectError("Synthetic unavailable target")

    monkeypatch.setattr(setup, "mcp_catalog", not_ready)
    from types import SimpleNamespace

    clock = iter([0, 26])
    monkeypatch.setattr(
        setup,
        "time",
        SimpleNamespace(time=setup.time.time, monotonic=lambda: next(clock), sleep=lambda _: None),
    )
    body = payload()
    assert client.post(URL, json=body).status_code == 502
    assert len(effects) == 1
    with factory() as db:
        row = db.get(Integration, profile_id)
        assert not row.enabled and not row.writes_enabled
        assert json.loads(row.last_check)["status"] == "pending"


def test_network_disabled_setup_does_not_mutate_broker_or_profile(bridge):
    from dataclasses import replace

    client, factory, cfg, profile_id, effects = bridge
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    setup.install_proton_bridge_setup(app, replace(cfg, integration_targets_enabled=False), factory)
    with TestClient(app) as c:
        assert c.post(URL, json=payload()).status_code == 403
    assert not effects
    with factory() as db:
        assert db.get(Integration, profile_id).revision == 1


def test_revocation_during_readiness_wait_prevents_activation(bridge, monkeypatch):
    import httpx

    client, factory, cfg, profile_id, effects = bridge
    probes = []

    def revoked(*args):
        probes.append("catalog")
        with factory() as db:
            row = db.get(Integration, profile_id)
            row.revision += 1
            db.commit()
        raise httpx.ConnectError("Synthetic pending rule")

    monkeypatch.setattr(setup, "mcp_catalog", revoked)
    monkeypatch.setattr(setup.time, "sleep", lambda _: None)
    result = client.post(URL, json=payload())
    assert result.status_code == 502 and probes == ["catalog"] and len(effects) == 1
    with factory() as db:
        row = db.get(Integration, profile_id)
        assert not row.enabled and not row.writes_enabled and row.revision == 3
        assert db.get(AgentPolicy, profile_id) is None


def test_revocation_during_broker_status_read_prevents_single_configuration_post(
    bridge, monkeypatch
):
    client, factory, cfg, profile_id, effects = bridge
    original = setup.control

    def status_then_revoked(cfg, body=None):
        assert body is None, "Revoked setup must never configure the broker"
        state = original(cfg)
        with factory() as db:
            row = db.get(Integration, profile_id)
            row.revision += 1
            db.commit()
        return state

    monkeypatch.setattr(setup, "control", status_then_revoked)
    assert client.post(URL, json=payload()).status_code == 502
    assert not effects
    with factory() as db:
        assert not db.get(Integration, profile_id).enabled


def test_successful_catalog_still_requires_final_current_pending_revision(bridge, monkeypatch):
    client, factory, cfg, profile_id, effects = bridge
    original = setup.mcp_catalog

    def catalog_then_revoked(*args):
        result = original(*args)
        with factory() as db:
            row = db.get(Integration, profile_id)
            row.revision += 1
            db.commit()
        return result

    monkeypatch.setattr(setup, "mcp_catalog", catalog_then_revoked)
    assert client.post(URL, json=payload()).status_code == 502
    assert len(effects) == 1
    with factory() as db:
        assert not db.get(Integration, profile_id).enabled
        assert db.get(AgentPolicy, profile_id) is None
