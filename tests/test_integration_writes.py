"""Grant/revision/privacy/replay guarantees at the external write boundary."""

import base64
import json
import time
from uuid import uuid4

import pytest
from hub import integration_write_adapters as adapters
from hub.db import ActionGrant, ActionIntent, ActionPolicy
from hub.integrations import Integration, IntegrationWriteAudit
from hub.provider_settings import encrypt
from test_actions import approve, execute, gateway, set_pause  # noqa: F401


@pytest.fixture
def writes(gateway, tmp_path, monkeypatch):  # noqa: F811
    app, client, headers, cfg = gateway
    key = tmp_path / "integration-key"
    key.write_text(base64.b64encode(b"w" * 32).decode())
    key.chmod(0o600)
    object.__setattr__(cfg, "secrets_key_file", str(key))
    object.__setattr__(cfg, "integration_targets_enabled", True)
    factory = app.state.sessions
    with factory() as db:
        row = Integration(
            name="Synthetic archive",
            kind="paperless",
            enabled=True,
            writes_enabled=True,
            config=json.dumps(
                dict(kind="paperless", url="https://archive.example.test", auth="api_key")
            ),
        )
        db.add(row)
        db.flush()
        row.encrypted_secret = encrypt(cfg, "integration:" + row.id, "synthetic-write-token")
        db.commit()
        identifier = row.id
    state = {
        "id": 1,
        "modified": "v1",
        "title": "Before",
        "tags": [],
        "correspondent": None,
        "document_type": None,
    }
    effects = []
    monkeypatch.setattr(adapters, "snapshot", lambda *a: dict(state))

    def apply(*a):
        effects.append(a[5])
        state.update(title=a[4]["title"], modified="v2")

    monkeypatch.setattr(adapters, "apply", apply)
    return app, client, headers, cfg, identifier, state, effects


def prepare(writes, **changes):
    app, c, h, cfg, i, state, effects = writes
    body = {
        "expected_revision": 1,
        "operation": "document.update_metadata",
        "arguments": {"document_id": 1, "title": "After"},
        **changes,
    }
    p = c.post(f"/api/integrations/{i}/write-preview", json=body, headers=h)
    assert p.status_code == 200, p.text
    r = c.post(
        "/api/actions",
        json={
            "request_id": str(uuid4()),
            "tool_id": "integration.write",
            "parameters": p.json()["parameters"],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_preview_no_write_and_success_replay(writes):
    app, c, h, cfg, i, state, effects = writes
    set_pause(c, h, False)
    action = prepare(writes)
    assert not effects and "synthetic-write-token" not in json.dumps(action)
    assert approve(c, h, action).status_code == 200
    result = execute(c, h, action)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded" and state["title"] == "After"
    set_pause(c, h, True)
    assert execute(c, h, action).json() == result.json()
    assert len(effects) == 1
    with app.state.sessions() as db:
        audit = db.get(IntegrationWriteAudit, action["id"])
        assert json.loads(audit.before_state)["title"] == "Before"


@pytest.mark.parametrize(
    "cause",
    [
        "pause",
        "expiry",
        "revoke",
        "profile",
        "disable",
        "write_disable",
        "drift",
        "hash",
        "tool_revision",
        "label",
    ],
)
def test_changed_authority_or_target_never_dispatches(writes, cause):
    app, c, h, cfg, i, state, effects = writes
    set_pause(c, h, False)
    a = prepare(writes)
    assert approve(c, h, a).status_code == 200
    with app.state.sessions() as db:
        row = db.get(ActionIntent, a["id"])
        profile = db.get(Integration, i)
        grant = db.get(ActionGrant, a["id"])
        if cause == "pause":
            db.get(ActionPolicy, 1).paused = True
        elif cause == "expiry":
            grant.expires = time.time() - 1
        elif cause == "revoke":
            grant.revoked = True
        elif cause == "profile":
            profile.revision += 1
        elif cause == "disable":
            profile.enabled = False
        elif cause == "write_disable":
            profile.writes_enabled = False
        elif cause == "hash":
            row.parameters_sha256 = "0" * 64
        elif cause == "tool_revision":
            row.tool_revision += 1
        elif cause == "label":
            row.label = "CLOUD_ALLOWED"
        db.commit()
    if cause == "drift":
        state["modified"] = "concurrent-change"
    r = execute(c, h, a)
    assert r.status_code in (403, 409), r.text
    assert not effects


def test_no_effect_without_grant(writes):
    _, c, h, _, _, _, effects = writes
    set_pause(c, h, False)
    a = prepare(writes)
    assert execute(c, h, a).status_code == 403
    assert not effects


def test_uncertain_dispatch_not_repeated_and_read_reconciliation(writes, monkeypatch):
    app, c, h, cfg, i, state, effects = writes
    set_pause(c, h, False)
    a = prepare(writes)
    approve(c, h, a)

    def lost(*args):
        effects.append(args[5])
        state["title"] = "After"
        raise TimeoutError("secret must not leak")

    monkeypatch.setattr(adapters, "apply", lost)
    r = execute(c, h, a)
    assert r.json()["status"] == "uncertain"
    assert "secret must not leak" not in r.text
    assert execute(c, h, a).json()["status"] == "uncertain" and len(effects) == 1
    set_pause(c, h, True)
    r = c.post("/api/actions/" + a["id"] + "/reconcile-integration", json={}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "reconciled"
    assert r.json()["receipt"]["causation_verified"] is False and len(effects) == 1


def test_crash_after_intent_never_replays(writes):
    app, c, h, _, _, _, effects = writes
    set_pause(c, h, False)
    a = prepare(writes)
    approve(c, h, a)
    with app.state.sessions() as db:
        db.get(ActionIntent, a["id"]).status = "dispatching"
        db.commit()
    assert execute(c, h, a).json()["status"] == "dispatching" and not effects


def test_unmatched_reconciliation_stays_uncertain(writes, monkeypatch):
    _, c, h, _, _, _, effects = writes
    set_pause(c, h, False)
    a = prepare(writes)
    approve(c, h, a)
    monkeypatch.setattr(adapters, "apply", lambda *a: (_ for _ in ()).throw(TimeoutError()))
    execute(c, h, a)
    r = c.post("/api/actions/" + a["id"] + "/reconcile-integration", json={}, headers=h)
    assert r.json()["status"] == "uncertain" and not effects


def test_profile_write_permission_and_revision(writes):
    _, c, h, _, i, _, _ = writes
    r = c.patch(
        f"/api/integrations/{i}/write-control",
        json={"expected_revision": 1, "writes_enabled": False},
        headers=h,
    )
    assert r.json() == {"writes_enabled": False, "revision": 2}
    assert (
        c.post(
            f"/api/integrations/{i}/write-preview",
            json={
                "expected_revision": 2,
                "operation": "document.update_metadata",
                "arguments": {"document_id": 1, "title": "After"},
            },
            headers=h,
        ).status_code
        == 403
    )
    assert (
        c.patch(
            f"/api/integrations/{i}/write-control",
            json={"expected_revision": 1, "writes_enabled": True},
            headers=h,
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "kind,op,args",
    [
        ("ssh", "file.write_text", {"filename": "../../authorized_keys", "content": "x"}),
        ("ssh", "exec", {"command": "whoami"}),
        ("home_assistant", "entity.set_power", {"entity_id": "lock.front_door", "state": "on"}),
        (
            "home_assistant",
            "entity.set_power",
            {"entity_id": "switch.test", "state": "on", "url": "https://evil.test"},
        ),
        ("paperless", "document.update_metadata", {"document_id": 1, "tags": [-1]}),
        ("paperless", "document.delete", {"document_id": 1}),
        ("paperless", "document.update_metadata", {"document_id": 1}),
    ],
)
def test_fixed_operations_reject_unreviewed_arguments(kind, op, args):
    with pytest.raises(ValueError):
        adapters.validate_arguments(kind, op, args)


def test_mcp_schema_subset_rejects_refs_regex_open_objects_and_wrong_types():
    good = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"title": {"type": "string", "maxLength": 20}},
        "required": ["title"],
    }
    adapters.validate_mcp_value(good, {"title": "Hello"})
    for schema, value in [
        (good, {"title": "x", "extra": 1}),
        (good, {}),
        ({"$ref": "https://evil.test"}, {}),
        ({"type": "string", "pattern": "(a+)+$"}, "a"),
        ({"type": "object"}, {}),
        ({"type": "integer"}, True),
    ]:
        with pytest.raises(ValueError):
            adapters.validate_mcp_value(schema, value)


def test_local_ai_draft_is_inert_private_and_idempotent(writes, monkeypatch):
    from hub.db import Message, Run
    from hub.integrations import IntegrationWriteDraft

    app, c, h, cfg, identifier, state, effects = writes
    monkeypatch.setattr("hub.integration_write_drafts.start_development", lambda *a: None)
    body = {
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "operation": "document.update_metadata",
        "prompt": "Benenne Dokument 1 in Nachweis um",
    }
    response = c.post(f"/api/integrations/{identifier}/write-drafts", json=body, headers=h)
    assert response.status_code == 200, response.text
    draft = response.json()
    repeated = c.post(f"/api/integrations/{identifier}/write-drafts", json=body, headers=h).json()
    assert repeated["id"] == draft["id"] and not effects
    changed = c.post(
        f"/api/integrations/{identifier}/write-drafts",
        json={**body, "prompt": "Anderer Auftrag"},
        headers=h,
    )
    assert changed.status_code == 409
    with app.state.sessions() as db:
        item = db.get(IntegrationWriteDraft, draft["id"])
        run = db.get(Run, item.run_id)
        snapshot = json.loads(run.context_snapshot)
        assert snapshot["model_local_only"] is True and snapshot["web_search_allowed"] is False
        assert all(p["label"] == "LOCAL_ONLY" for p in snapshot["parts"])
        assert (
            "synthetic-write-token" not in run.context_snapshot
            and "archive.example.test" not in run.context_snapshot
        )
        run.status = "succeeded"
        db.add(
            Message(
                conversation_id=item.conversation_id,
                run_id=run.id,
                role="assistant",
                content=json.dumps(
                    {
                        "message": "Bitte prüfen.",
                        "arguments": {"document_id": 1, "title": "Nachweis"},
                    }
                ),
                label="LOCAL_ONLY",
            )
        )
        db.commit()
    result = c.get("/api/integration-write-drafts/" + draft["id"]).json()
    assert result["arguments"] == {"document_id": 1, "title": "Nachweis"} and not effects
    with app.state.sessions() as db:
        db.get(Integration, identifier).revision += 1
        db.commit()
    result = c.get("/api/integration-write-drafts/" + draft["id"]).json()
    assert result["profile_current"] is False and result["arguments"] is None


def test_model_output_cannot_create_tools_or_parameters(writes, monkeypatch):
    from hub.db import Message, Run
    from hub.integrations import IntegrationWriteDraft

    app, c, h, cfg, identifier, state, effects = writes
    monkeypatch.setattr("hub.integration_write_drafts.start_development", lambda *a: None)
    body = {
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "operation": "document.update_metadata",
        "prompt": "Test",
    }
    draft = c.post(f"/api/integrations/{identifier}/write-drafts", json=body, headers=h).json()
    with app.state.sessions() as db:
        item = db.get(IntegrationWriteDraft, draft["id"])
        run = db.get(Run, item.run_id)
        run.status = "succeeded"
        db.add(
            Message(
                conversation_id=item.conversation_id,
                run_id=run.id,
                role="assistant",
                content=json.dumps(
                    {
                        "message": "Do it",
                        "arguments": {"document_id": 1, "title": "Test", "command": "rm -rf /"},
                    }
                ),
                label="LOCAL_ONLY",
            )
        )
        db.commit()
    result = c.get("/api/integration-write-drafts/" + draft["id"]).json()
    assert result["arguments"] is None and result["validation_error"] and not effects


def test_target_change_resets_profile_write_permission(writes):
    app, c, h, cfg, identifier, state, effects = writes
    r = c.put(
        "/api/integrations/" + identifier,
        json={
            "name": "Synthetic moved target",
            "kind": "paperless",
            "url": "https://other.example.test",
            "auth": "api_key",
            "secret": "new-synthetic-key",
            "expected_revision": 1,
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["writes_enabled"] is False and r.json()["secret_saved"] is True


def test_revocation_cannot_hide_unknown_effect(writes, monkeypatch):
    _, c, h, _, _, _, _ = writes
    set_pause(c, h, False)
    a = prepare(writes)
    approve(c, h, a)
    monkeypatch.setattr(adapters, "apply", lambda *a: (_ for _ in ()).throw(TimeoutError()))
    assert execute(c, h, a).json()["status"] == "uncertain"
    r = c.post("/api/actions/" + a["id"] + "/revoke", json={}, headers=h)
    assert r.status_code == 409
    assert execute(c, h, a).json()["status"] == "uncertain"


def test_grant_expiry_during_transport_setup_stops_final_effect(writes, monkeypatch):
    _, c, h, _, _, _, effects = writes
    set_pause(c, h, False)
    action = prepare(writes)
    approve(c, h, action)
    now = time.time()

    def setup(*args):
        monkeypatch.setattr("hub.integration_writes.time.time", lambda: now + 400)
        args[6]()
        effects.append(args[5])

    monkeypatch.setattr(adapters, "apply", setup)
    result = execute(c, h, action)
    assert result.json()["status"] == "uncertain" and not effects
