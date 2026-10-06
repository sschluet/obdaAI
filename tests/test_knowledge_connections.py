import asyncio
import json
import time

import pytest
import test_artifact_api
from hub.db import KnowledgeConnection, Project, Source
from hub.knowledge import context
from hub.knowledge_clients import ConnectionInput, Document, resolve_host
from hub.knowledge_connections import index_connection
from hub.provider_settings import decrypt
from sqlalchemy import select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_artifact_api.setup.__wrapped__(tmp_path, monkeypatch)


def create(c, h, **changes):
    r = c.post(
        "/api/knowledge-sources",
        headers=h,
        json={
            "name": "Synthetic external source",
            "kind": "smb",
            "server": "192.0.2.10",
            "share": "Documents",
            "username": "synthetic-user",
            "password": "synthetic-rag-password",
            **changes,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def wait_ready(c, source):
    for _ in range(160):
        fresh = next(r for r in c.get("/api/knowledge-sources").json() if r["id"] == source["id"])
        if fresh["indexed"] and not fresh["pending"]:
            return fresh
        time.sleep(0.025)
    pytest.fail("Synthetic knowledge snapshot did not become ready")


def test_secret_is_encrypted_hidden_project_is_separate_and_never_cloud_enabled(setup):
    app, c, h, cfg, pid, spec = setup
    source = create(c, h)
    assert (
        not source["enabled"]
        and source["secret_set"]
        and "password" not in source["config"]
        and "synthetic-rag-password" not in json.dumps(source)
    )
    assert source["project_id"] not in [p["id"] for p in c.get("/api/projects").json()]
    assert (
        c.post(
            "/api/conversations", headers=h, json={"project_id": source["project_id"]}
        ).status_code
        == 409
    )
    with app.state.sessions() as db:
        row = db.get(KnowledgeConnection, source["id"])
        assert decrypt(cfg, "knowledge:" + row.id, row.encrypted_secret) == "synthetic-rag-password"
        assert db.get(Project, row.project_id).kind == "knowledge"
    changed = source["config"] | {"revision": source["revision"], "server": "192.0.2.11"}
    assert (
        c.put("/api/knowledge-sources/" + source["id"], headers=h, json=changed).status_code == 422
    )


def test_readonly_index_is_scoped_idempotent_and_revocable(setup, monkeypatch):
    app, c, h, cfg, pid, spec = setup

    def fake(body, password, *, probe=False):
        assert password == "synthetic-rag-password" and body.share == "Documents"
        yield Document("folder/evidence.txt", b"EXTERNAL_SOURCE_BLUE_SEVEN")

    monkeypatch.setattr("hub.knowledge_connections.documents", fake)
    source = create(c, h)
    assert c.post(
        "/api/knowledge-sources/" + source["id"] + "/test",
        headers=h,
        json={"revision": source["revision"], "enabled": True},
    ).json()["ok"]
    assert (
        c.post(
            "/api/knowledge-sources/" + source["id"] + "/index",
            json={"revision": 1, "enabled": True},
        ).status_code
        == 403
    )
    r = c.post(
        "/api/knowledge-sources/" + source["id"] + "/index",
        headers=h,
        json={"revision": 1, "enabled": True},
    )
    assert r.status_code == 200
    source = wait_ready(c, source)
    assert source["chat_ready"] and source["indexed"] == 1
    with app.state.sessions() as db:
        parts = context(db, source["project_id"], "BLUE")
        assert any("EXTERNAL_SOURCE_BLUE_SEVEN" in p.content for p in parts)
        assert all(p.label == "LOCAL_ONLY" for p in parts)
        assert not any("EXTERNAL_SOURCE_BLUE_SEVEN" in p.content for p in context(db, pid, "BLUE"))
    cid = c.post("/api/conversations", headers=h, json={"project_id": source["project_id"]})
    assert cid.status_code == 200
    assert (
        c.post(
            "/api/conversations",
            headers=h,
            json={"project_id": source["project_id"], "cloud_allowed": True},
        ).status_code
        == 409
    )
    indexed = c.post(
        "/api/knowledge-sources/" + source["id"] + "/index",
        headers=h,
        json={"revision": source["revision"], "enabled": True},
    )
    assert indexed.status_code == 200
    source = wait_ready(c, source)
    with app.state.sessions() as db:
        assert (
            len(list(db.scalars(select(Source).where(Source.project_id == source["project_id"]))))
            == 1
        )
    stopped = c.patch(
        "/api/knowledge-sources/" + source["id"] + "/control",
        headers=h,
        json={"revision": source["revision"], "enabled": False},
    )
    assert stopped.status_code == 200
    assert (
        c.post(
            "/api/conversations", headers=h, json={"project_id": source["project_id"]}
        ).status_code
        == 404
    )
    with app.state.sessions() as db:
        with pytest.raises(ValueError):
            context(db, source["project_id"], "BLUE")


def test_new_scan_revision_cannot_be_resumed_by_old_delivery_and_rebind_retires_old_scope(
    setup, monkeypatch
):
    app, c, h, cfg, pid, spec = setup

    def fake(body, password, *, probe=False):
        yield Document("evidence.txt", b"BOUND_ORIGINAL")

    monkeypatch.setattr("hub.knowledge_connections.documents", fake)
    source = create(c, h)
    c.post(
        "/api/knowledge-sources/" + source["id"] + "/index",
        headers=h,
        json={"revision": source["revision"], "enabled": True},
    )
    source = wait_ready(c, source)
    with app.state.sessions() as db:
        row = db.get(KnowledgeConnection, source["id"])
        row.status = "indexing"
        row.revision += 1
        new_revision = row.revision
        db.commit()
    asyncio.run(index_connection(app.state.sessions, cfg, source["id"], new_revision - 1))
    with app.state.sessions() as db:
        assert db.get(KnowledgeConnection, source["id"]).status == "indexing"
    with app.state.sessions() as db:
        db.get(KnowledgeConnection, source["id"]).status = "ready"
        db.commit()
    changed = source["config"] | {
        "revision": new_revision,
        "server": "192.0.2.11",
        "password": "new-synthetic-password",
    }
    r = c.put("/api/knowledge-sources/" + source["id"], headers=h, json=changed)
    assert r.status_code == 200, r.text
    with app.state.sessions() as db:
        assert all(
            s.status == "superseded"
            for s in db.scalars(select(Source).where(Source.project_id == source["project_id"]))
        )


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "::1", "0.0.0.0", "224.0.0.1"])
def test_native_connection_blocks_system_targets_before_transport(monkeypatch, ip):
    monkeypatch.setattr(
        "hub.knowledge_clients.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (ip, 445))]
    )
    with pytest.raises(ValueError):
        resolve_host("server.example", 445)


@pytest.mark.parametrize(
    "change",
    [
        {"folder": "../private"},
        {"folder": ".obsidian"},
        {"server": "http://server/path"},
        {"kind": "sql", "database": "data", "table": "orders; DELETE"},
        {"kind": "nfs", "share": "/export/../private"},
    ],
)
def test_free_configuration_never_becomes_shell_path_or_sql(change):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ConnectionInput.model_validate(
            {
                "name": "Test",
                "kind": "smb",
                "server": "192.0.2.10",
                "share": "Docs",
                "username": "user",
                **change,
            }
        )
