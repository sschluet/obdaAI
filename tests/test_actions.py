import concurrent.futures
import json
import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import ActionGrant, ActionIntent, ActionReceipt, Project
from sqlalchemy import func, select


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "actions.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    cfg = Settings(
        database_url=url,
        origin="http://testserver",
        secure_cookie=False,
        password_hash=password_hash("synthetic-action-password"),
    )
    app = create_app(cfg)
    with TestClient(app) as c:
        login = c.post(
            "/api/login",
            json={"password": "synthetic-action-password"},
            headers={"Origin": cfg.origin},
        )
        headers = {"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]}
        yield app, c, headers, cfg


def set_pause(c, h, value):
    policy = c.get("/api/action-policy").json()
    return c.patch(
        "/api/action-policy",
        json={"paused": value, "expected_revision": policy["revision"]},
        headers=h,
    )


def proposal(c, h, project=None, request_id=None):
    body = {
        "request_id": request_id or str(uuid.uuid4()),
        "tool_id": "hub.inspect",
        "parameters": {},
    }
    if project:
        body.update(
            tool_id="project.archive",
            parameters={"project_id": project["id"], "expected_revision": project["revision"]},
        )
    r = c.post("/api/actions", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json(), body


def approve(c, h, action):
    return c.post(
        "/api/actions/" + action["id"] + "/grant",
        headers=h,
        json={
            "parameters_sha256": action["parameters_sha256"],
            "tool_revision": action["tool_revision"],
        },
    )


def execute(c, h, action):
    return c.post("/api/actions/" + action["id"] + "/execute", json={}, headers=h)


def project(c, h):
    return c.post("/api/projects", headers=h, json={"name": "Synthetic gateway project"}).json()


def test_gateway_read_and_strict_schema_before_effect(gateway):
    app, c, h, cfg = gateway
    assert c.get("/api/action-policy").json() == {"paused": True, "revision": 1}
    assert len(c.get("/api/tools").json()) == 2
    action, body = proposal(c, h)
    result = execute(c, h, action)
    assert result.status_code == 200 and result.json()["receipt"]["label"] == "LOCAL_ONLY"
    assert execute(c, h, action).json() == result.json()
    for tool_id, params in [
        ("shell", {}),
        ("hub.inspect", {"url": "http://127.0.0.1"}),
        ("project.archive", {"project_id": "invalid", "expected_revision": 1}),
    ]:
        changed = {
            **body,
            "request_id": str(uuid.uuid4()),
            "tool_id": tool_id,
            "parameters": params,
        }
        assert c.post("/api/actions", json=changed, headers=h).status_code == 422
    assert (
        c.post("/api/actions", json={**body, "label": "CLOUD_ALLOWED"}, headers=h).status_code
        == 422
    )
    assert (
        c.post(
            "/api/actions/" + action["id"] + "/execute", json={"parameters": {}}, headers=h
        ).status_code
        == 422
    )


def test_gateway_exact_approval_and_concurrent_duplicate_execution(gateway):
    app, c, h, cfg = gateway
    p = project(c, h)
    action, _ = proposal(c, h, p)
    assert execute(c, h, action).status_code == 409
    assert approve(c, h, action).status_code == 409
    assert set_pause(c, h, False).status_code == 200
    assert approve(c, h, action).status_code == 409  # Pause transition invalidates old proposals.
    action, body = proposal(c, h, p)
    assert c.post("/api/actions", json=body, headers=h).json()["id"] == action["id"]
    other_project = project(c, h)
    changed = {**body, "parameters": {"project_id": other_project["id"], "expected_revision": 1}}
    assert c.post("/api/actions", json=changed, headers=h).status_code == 409
    assert execute(c, h, action).status_code == 403
    bad = {**action, "parameters_sha256": "0" * 64}
    assert approve(c, h, bad).status_code == 409
    assert approve(c, h, action).status_code == 200
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(c, h, action), range(2)))
    assert all(r.status_code == 200 for r in results)
    assert results[0].json()["receipt"] == results[1].json()["receipt"]
    with app.state.sessions() as db:
        saved = db.get(Project, p["id"])
        assert saved.archived and saved.revision == p["revision"] + 1
        assert db.scalar(select(func.count()).select_from(ActionReceipt)) == 1
    assert set_pause(c, h, True).status_code == 200
    assert execute(c, h, action).status_code == 200  # Existing receipt, no new write.
    assert c.post("/api/actions", json={**body, "parameters": {}}, headers=h).status_code == 422


@pytest.mark.parametrize(
    "reason",
    [
        "expired",
        "revoked",
        "pause_cycle",
        "target_changed",
        "parameters_changed",
        "tool_changed",
        "privacy_changed",
    ],
)
def test_gateway_final_boundary_rejects_stale_or_revoked_authority(gateway, reason):
    app, c, h, cfg = gateway
    set_pause(c, h, False)
    p = project(c, h)
    action, body = proposal(c, h, p)
    assert approve(c, h, action).status_code == 200
    if reason == "revoked":
        assert (
            c.post("/api/actions/" + action["id"] + "/revoke", json={}, headers=h).status_code
            == 200
        )
    elif reason == "pause_cycle":
        set_pause(c, h, True)
        set_pause(c, h, False)
    elif reason == "target_changed":
        assert (
            c.patch(
                "/api/projects/" + p["id"],
                json={
                    "name": "Changed by another editor",
                    "revision": p["revision"],
                },
                headers=h,
            ).status_code
            == 200
        )
    else:
        with app.state.sessions() as db:
            row = db.get(ActionIntent, action["id"])
            if reason == "expired":
                db.get(ActionGrant, row.id).expires = 0
            elif reason == "parameters_changed":
                row.parameters = json.dumps({**body["parameters"], "expected_revision": 999})
            elif reason == "tool_changed":
                row.tool_revision += 1
            elif reason == "privacy_changed":
                row.label = "CLOUD_ALLOWED"
            db.commit()
    assert execute(c, h, action).status_code in {403, 409}
    with app.state.sessions() as db:
        assert not db.get(Project, p["id"]).archived
        assert db.get(ActionReceipt, action["id"]) is None


def test_gateway_restart_preserves_grant_pause_and_receipt(gateway):
    app, c, h, cfg = gateway
    set_pause(c, h, False)
    p = project(c, h)
    action, _ = proposal(c, h, p)
    approve(c, h, action)
    restarted = create_app(cfg)
    with TestClient(restarted) as other:
        other.cookies.update(c.cookies)
        assert execute(other, h, action).status_code == 200
        set_pause(other, h, True)
    again = create_app(cfg)
    with TestClient(again) as other:
        other.cookies.update(c.cookies)
        assert other.get("/api/action-policy").json()["paused"]
        assert execute(other, h, action).status_code == 200


def test_gateway_authentication_csrf_and_pause_revision(gateway):
    app, c, h, cfg = gateway
    with TestClient(create_app(cfg)) as other:
        assert other.get("/api/tools").status_code == 401
        assert other.post("/api/actions", json={}).status_code == 401
    assert (
        c.patch("/api/action-policy", json={"paused": False, "expected_revision": 1}).status_code
        == 403
    )
    set_pause(c, h, False)
    assert (
        c.patch(
            "/api/action-policy", json={"paused": True, "expected_revision": 1}, headers=h
        ).status_code
        == 409
    )


def test_action_audit_blocks_destructive_schema_downgrade(gateway):
    app, c, h, cfg = gateway
    proposal(c, h)
    with pytest.raises(RuntimeError, match="Preserve action audit"):
        command.downgrade(Config("alembic.ini"), "0011")
    assert len(c.get("/api/actions").json()) == 1
