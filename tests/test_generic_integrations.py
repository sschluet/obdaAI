"""Registry secrecy, explicit selections and bounded target checks."""

import base64
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hub.auth import require_session
from hub.config import Settings
from hub.db import Base, Conversation, Project, Task, session_factory
from hub.integration_api import freeze_bindings, install_integration_api
from hub.integrations import Integration
from hub.provider_settings import decrypt


@pytest.fixture
def registry(tmp_path):
    key = tmp_path / "key"
    key.write_text(base64.b64encode(b"s" * 32).decode())
    key.chmod(0o600)
    cfg = Settings(
        database_url="sqlite:///" + str(tmp_path / "registry.sqlite"), secrets_key_file=str(key)
    )
    factory = session_factory(cfg.database_url)
    Base.metadata.create_all(factory.kw["bind"])
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    install_integration_api(app, cfg, factory)
    with TestClient(app) as client:
        yield client, factory, cfg


def draft(**changes):
    return {
        "name": "Synthetic connector",
        "kind": "paperless",
        "url": "https://paperless.example.test",
        "auth": "api_key",
        **changes,
    }


def create(client, **changes):
    response = client.post("/api/integrations", json=draft(**changes))
    assert response.status_code == 200, response.text
    return response.json()


def test_secret_never_public_and_target_drift_clears(registry):
    c, factory, cfg = registry
    row = create(c, secret="synthetic-token")
    assert row["enabled"] is False and row["secret_saved"] is True
    assert "synthetic-token" not in json.dumps(row)
    assert "synthetic-token" not in c.get("/api/integrations").text
    with factory() as db:
        stored = db.get(Integration, row["id"])
        assert stored and stored.encrypted_secret
        assert (
            decrypt(cfg, "integration:" + row["id"], stored.encrypted_secret) == "synthetic-token"
        )
        assert "synthetic-token" not in stored.config
    edited = c.put(
        "/api/integrations/" + row["id"],
        json=draft(expected_revision=1, url="https://another.example.test"),
    ).json()
    assert edited["revision"] == 2 and edited["secret_saved"] is False
    assert (
        c.put("/api/integrations/" + row["id"], json=draft(expected_revision=1)).status_code == 409
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "https://user:secret@example.test"},
        {"url": "https://example.test/?token=secret"},
        {"url": "file:///etc/passwd"},
        {"url": "http://user:secret@192.168.1.2"},
        {"url": "https://example.test/#fragment"},
        {"auth": "password"},
        {"username": "user"},
        {"secret": "bad\r\nheader"},
        {"secret": "x", "clear_secret": True},
        {
            "kind": "ssh",
            "auth": "private_key",
            "url": "-oProxyCommand=test",
            "username": "user",
            "host_key": "ssh-ed25519 AAAA",
        },
        {"kind": "ssh", "auth": "password", "url": "server.example.test", "username": "user"},
    ],
)
def test_invalid_typed_targets_and_auth_rejected(registry, changes):
    c, _, _ = registry
    assert c.post("/api/integrations", json=draft(**changes)).status_code == 422
    assert c.get("/api/integrations").json()["integrations"] == []


@pytest.mark.parametrize(
    "kind,auth",
    [
        ("home_assistant", "bearer"),
        ("paperless", "api_key"),
        ("unifi", "api_key"),
        ("mcp", "none"),
        ("ssh", "private_key"),
    ],
)
def test_all_types_save_without_network_and_check_blocked(registry, monkeypatch, kind, auth):
    c, _, _ = registry
    monkeypatch.setattr("hub.integration_api.httpx.Client", lambda **kw: pytest.fail("No network"))
    extras = (
        {
            "url": "server.example.test",
            "username": "synthetic",
            "host_key": "ssh-ed25519 AAAA",
            "secret": "synthetic-key",
        }
        if kind == "ssh"
        else {}
    )
    if kind == "mcp":
        extras["url"] = "https://example.test/mcp"
    row = create(c, kind=kind, auth=auth, **extras)
    checked = c.post(
        "/api/integrations/" + row["id"] + "/check", json={"expected_revision": 1}
    ).json()
    assert checked["last_check"]["status"] == "blocked"
    assert checked["execution_available"] is False and checked["target_approved"] is False


def test_binding_cas_inheritance_disable_and_owner_isolation(registry):
    c, factory, _ = registry
    integration = create(c)
    with factory() as db:
        project = Project(name="Synthetic project")
        db.add(project)
        db.flush()
        conversation = Conversation(project_id=project.id)
        task = Task()
        db.add_all([conversation, task])
        db.commit()
        pid, cid, tid = project.id, conversation.id, task.id
    project_url = "/api/integration-bindings/project/" + pid
    conversation_url = "/api/integration-bindings/conversation/" + cid
    body = {
        "expected_revision": 0,
        "integration_ids": [integration["id"]],
        "selection_mode": "automatic",
    }
    selected = c.put(project_url, json=body).json()
    assert selected["integration_ids"] == [integration["id"]]
    assert selected["effective_integration_ids"] == []
    assert c.put(project_url, json=body).status_code == 409
    enabled = c.patch(
        "/api/integrations/" + integration["id"] + "/control",
        json={"enabled": True, "expected_revision": 1},
    ).json()
    assert enabled["revision"] == 2
    inherited = c.get(conversation_url).json()
    assert inherited["selection_mode"] == "inherit" and inherited["revision"] == 0
    assert inherited["effective_integration_ids"] == [integration["id"]]
    with factory() as db:
        frozen = freeze_bindings(db, "conversation", cid)
        assert frozen["bindings"][0]["revision"] == 2
        assert "config" not in json.dumps(frozen) and "secret" not in json.dumps(frozen)
    assert (
        c.put(
            conversation_url,
            json={"expected_revision": 0, "integration_ids": [], "selection_mode": "off"},
        ).json()["effective_integration_ids"]
        == []
    )
    assert c.get("/api/integration-bindings/task/" + tid).json()["integration_ids"] == []
    assert (
        c.put(
            "/api/integration-bindings/task/" + tid, json={**body, "selection_mode": "inherit"}
        ).status_code
        == 422
    )
    assert (
        c.patch(
            "/api/integrations/" + integration["id"] + "/control",
            json={"enabled": False, "expected_revision": 2},
        ).status_code
        == 200
    )
    assert c.get(project_url).json()["effective_integration_ids"] == []
    assert (
        c.patch(
            "/api/integrations/" + integration["id"] + "/control",
            json={"enabled": True, "expected_revision": 2},
        ).status_code
        == 409
    )
    assert (
        c.put(
            project_url, json={**body, "expected_revision": 1, "integration_ids": [str(uuid4())]}
        ).status_code
        == 404
    )
    with factory() as db:
        p = db.get(Project, pid)
        assert p
        p.archived = True
        db.commit()
    assert c.get(project_url).status_code == 404
    assert c.put(project_url, json={**body, "expected_revision": 1}).status_code == 404


def test_checked_revision_becomes_stale_after_control(registry, monkeypatch):
    c, _, cfg = registry
    object.__setattr__(
        cfg, "mcp_endpoints_json", json.dumps({"https://example.test/mcp": "1.1.1.1"})
    )
    monkeypatch.setattr("hub.integration_api.discover", lambda *a, **k: {"tools": []})
    row = create(c, kind="mcp", auth="none", url="https://example.test/mcp")
    checked = c.post(
        "/api/integrations/" + row["id"] + "/check", json={"expected_revision": 1}
    ).json()
    assert checked["last_check"]["status"] == "succeeded"
    enabled = c.patch(
        "/api/integrations/" + row["id"] + "/control",
        json={"enabled": True, "expected_revision": 1},
    ).json()
    assert enabled["status"] == "configured" and enabled["last_check"]["revision"] == 1


def test_delete_requires_cas_and_unbound_owner_and_counts(registry):
    c, factory, _ = registry
    row = create(c, secret="synthetic-key")
    with factory() as db:
        project = Project(name="Synthetic deletion owner")
        db.add(project)
        db.commit()
        pid = project.id
    path = "/api/integration-bindings/project/" + pid
    selection = c.put(
        path,
        json={"expected_revision": 0, "integration_ids": [row["id"]], "selection_mode": "manual"},
    )
    assert selection.status_code == 200
    assert c.get("/api/integrations").json()["integrations"][0]["binding_counts"] == {
        "project": 1,
        "task": 0,
        "conversation": 0,
    }

    def remove(revision):
        return c.request(
            "DELETE", "/api/integrations/" + row["id"], json={"expected_revision": revision}
        )

    assert remove(2).status_code == 409
    assert remove(1).status_code == 409
    assert (
        c.put(
            path, json={"expected_revision": 1, "integration_ids": [], "selection_mode": "off"}
        ).status_code
        == 200
    )
    assert remove(1).status_code == 200
    assert c.get("/api/integrations").json()["integrations"] == []
    with factory() as db:
        assert db.get(Integration, row["id"]) is None


def test_active_chat_task_runs_prevent_selection_mutation(registry):
    from hub.db import Run, TaskRun

    c, factory, _ = registry
    with factory() as db:
        project = Project(name="Synthetic active owner")
        db.add(project)
        db.flush()
        conversation = Conversation(project_id=project.id)
        task = Task()
        db.add_all([conversation, task])
        db.flush()
        db.add(Run(conversation_id=conversation.id, status="streaming"))
        db.add(
            TaskRun(
                task_id=task.id,
                task_revision=1,
                control_revision=1,
                request_key=str(uuid4()),
                request_digest="",
                snapshot="{}",
            )
        )
        db.commit()
        ids = {"project": project.id, "conversation": conversation.id, "task": task.id}
    for scope, owner in ids.items():
        assert (
            c.put(
                f"/api/integration-bindings/{scope}/{owner}",
                json={"expected_revision": 0, "integration_ids": [], "selection_mode": "off"},
            ).status_code
            == 409
        )


@pytest.mark.skipif(
    not __import__("os").getenv("HUB_CI_DATABASE_URL"),
    reason="Disposable PostgreSQL CI DB required",
)
def test_registry_and_binding_cas_postgres(monkeypatch):
    import concurrent.futures
    import os

    from alembic import command
    from alembic.config import Config
    from hub.integrations import IntegrationBinding
    from sqlalchemy import delete

    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Refusing any database except loopback hub_ci")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    cfg = Settings(
        database_url=url, mcp_endpoints_json=json.dumps({"https://example.test/mcp": "1.1.1.1"})
    )
    factory = session_factory(url)
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    install_integration_api(app, cfg, factory)
    with factory() as db:
        project = Project(name="Synthetic PG integration owner")
        db.add(project)
        db.commit()
        pid = project.id
    iid = None
    try:
        with TestClient(app) as c:
            row = create(c, kind="mcp", auth="none", url="https://example.test/mcp")
            iid = row["id"]
            path = "/api/integrations/" + iid
            with concurrent.futures.ThreadPoolExecutor() as pool:
                requests = [
                    pool.submit(
                        c.patch, path + "/control", json={"expected_revision": 1, "enabled": True}
                    )
                    for _ in range(2)
                ]
                assert sorted(r.result(timeout=10).status_code for r in requests) == [200, 409]
            binding_path = "/api/integration-bindings/project/" + pid
            with concurrent.futures.ThreadPoolExecutor() as pool:
                requests = [
                    pool.submit(
                        c.put,
                        binding_path,
                        json={
                            "expected_revision": 0,
                            "integration_ids": [iid],
                            "selection_mode": "manual",
                        },
                    )
                    for _ in range(2)
                ]
                assert sorted(r.result(timeout=10).status_code for r in requests) == [200, 409]

            def changed(*args, **kwargs):
                with factory() as db:
                    actual = db.get(Integration, iid)
                    assert actual
                    actual.revision += 1
                    db.commit()
                return {"tools": []}

            monkeypatch.setattr("hub.integration_api.discover", changed)
            assert c.post(path + "/check", json={"expected_revision": 2}).status_code == 409
            with factory() as db:
                actual = db.get(Integration, iid)
                assert actual and actual.last_check is None
    finally:
        with factory() as db:
            db.execute(
                delete(IntegrationBinding).where(
                    IntegrationBinding.scope == "project", IntegrationBinding.owner_id == pid
                )
            )
            if iid:
                db.execute(delete(Integration).where(Integration.id == iid))
            db.execute(delete(Project).where(Project.id == pid))
            db.commit()


def test_canonical_target_preserves_secret_but_real_drift_clears(registry):
    c, factory, _ = registry
    row = create(c, secret="synthetic-key", url="https://EXAMPLE.test:443/")
    assert row["config"]["url"] == "https://example.test"
    # Existing rows created before canonicalization may retain a trailing slash.
    with factory() as db:
        stored = db.get(Integration, row["id"])
        assert stored
        config = json.loads(stored.config)
        config["url"] = "https://EXAMPLE.test:443/"
        stored.config = json.dumps(config)
        db.commit()
    same = c.put(
        "/api/integrations/" + row["id"],
        json=draft(
            url="https://example.test/",
            expected_revision=1,
        ),
    ).json()
    assert same["secret_saved"] is True
    changed = c.put(
        "/api/integrations/" + row["id"],
        json=draft(
            url="https://example.test:8443",
            expected_revision=2,
        ),
    ).json()
    assert changed["secret_saved"] is False


def test_profile_read_check_uses_own_url_key_and_pinned_address(registry, monkeypatch):
    c, _, cfg = registry
    object.__setattr__(cfg, "integration_targets_enabled", True)
    monkeypatch.setattr(
        "hub.integration_transport.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("192.168.20.4", 8123))],
    )
    captured = []

    def read_check(client, token, **kwargs):
        captured.append((token, kwargs["network_target"]))
        return {"version": "synthetic"}

    monkeypatch.setattr("hub.integration_api.assessment", read_check)
    row = create(
        c,
        kind="home_assistant",
        auth="bearer",
        secret="synthetic-key",
        url="http://ha.example.test:8123/",
    )
    assert row["target_approved"] is True
    assert row["availability_reason"] == "disabled"
    path = "/api/integrations/" + row["id"]
    disabled = c.post(path + "/check", json={"expected_revision": 1}).json()
    assert disabled["last_check"]["status"] == "blocked" and not captured
    enabled = c.patch(path + "/control", json={"enabled": True, "expected_revision": 1}).json()
    assert enabled["check_available"] is True
    checked = c.post(path + "/check", json={"expected_revision": 2}).json()
    assert checked["status"] == "checked"
    assert captured == [
        (
            "synthetic-key",
            (
                "http://192.168.20.4:8123",
                {"Host": "ha.example.test:8123"},
                {"sni_hostname": "ha.example.test"},
            ),
        )
    ]
    assert checked["execution_available"] is False


def test_unifi_adapter_ready_is_separate_from_target_permission(registry):
    c, _, cfg = registry
    object.__setattr__(cfg, "integration_targets_enabled", True)
    row = create(c, kind="unifi", secret="synthetic-key", url="https://unifi.example.test")
    enabled = c.patch(
        "/api/integrations/" + row["id"] + "/control",
        json={"enabled": True, "expected_revision": 1},
    ).json()
    assert enabled["target_approved"] is True
    assert enabled["availability_reason"] == "ready"
    assert enabled["check_available"] is True


def test_mcp_exact_endpoint_slash_is_saved_and_not_a_credential_alias(registry):
    c, _, _ = registry
    row = create(
        c, kind="mcp", auth="bearer", url="https://mcp.test/mcp/", secret="synthetic-token"
    )
    assert row["config"]["url"] == "https://mcp.test/mcp/"
    changed = c.put(
        "/api/integrations/" + row["id"],
        json=draft(
            kind="mcp",
            auth="bearer",
            url="https://mcp.test/mcp",
            expected_revision=1,
        ),
    ).json()
    assert changed["secret_saved"] is False
