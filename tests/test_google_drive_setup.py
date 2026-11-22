"""Session-bound Drive OAuth, explicit capabilities and non-replaying token renewal."""

import base64
import json
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub import google_drive_client as drive
from hub import google_drive_setup as setup
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import LoginSession, session_factory
from hub.integrations import Integration
from sqlalchemy import select

SETUP = "/api/integrations/google-drive/setup"
CLIENT_ID = "synthetic-drive-client.apps.googleusercontent.com"
SECRET = "synthetic-client-secret-not-a-real-account"


@pytest.fixture
def context(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_text(base64.b64encode(b"k" * 32).decode())
    key.chmod(0o600)
    cfg = Settings(
        database_url="sqlite:///" + str(tmp_path / "drive.sqlite"),
        origin="http://127.0.0.1:18765",
        secure_cookie=False,
        password_hash=password_hash("synthetic-password"),
        secrets_key_file=str(key),
        integration_targets_enabled=True,
    )
    monkeypatch.setenv("HUB_DATABASE_URL", cfg.database_url)
    command.upgrade(Config("alembic.ini"), "head")
    app = create_app(cfg)
    if not any(r.path == SETUP for r in app.routes):
        setup.install_google_drive_setup(app, cfg, app.state.sessions)
    factory = session_factory(cfg.database_url)
    effects = []

    def exchange(
        client_id, client_secret, redirect_uri, code, verifier, requested_scopes, *, before_send
    ):
        before_send()
        effects.append("exchange")
        with factory() as db:
            intent = db.scalar(
                select(setup.GoogleDriveOAuthAttempt).where(
                    setup.GoogleDriveOAuthAttempt.operation == "oauth",
                    setup.GoogleDriveOAuthAttempt.status == "dispatching",
                )
            )
            assert intent and intent.encrypted_verifier is None
        return {
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
            "expires_at": time.time() + 3600,
            "scope": " ".join(sorted(requested_scopes)),
            "token_type": "Bearer",
        }

    monkeypatch.setattr(drive, "exchange_code", exchange)

    class Client:
        def __init__(self, token, *, before_send):
            self.before_send = before_send

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def about(self):
            self.before_send()
            effects.append("about")
            return {"emailAddress": "aurora@example.test"}

    monkeypatch.setattr(drive, "DriveClient", Client)

    def refresh(client_id, client_secret, refresh_token, requested_scopes, *, before_send):
        before_send()
        effects.append("refresh")
        return {
            "access_token": "synthetic-renewed",
            "refresh_token": refresh_token,
            "expires_at": time.time() + 3600,
            "scope": " ".join(sorted(requested_scopes)),
            "token_type": "Bearer",
        }

    monkeypatch.setattr(drive, "refresh_token", refresh)
    with TestClient(app, base_url=cfg.origin) as client:
        login = client.post(
            "/api/login", json={"password": "synthetic-password"}, headers={"Origin": cfg.origin}
        )
        assert login.status_code == 200
        headers = {"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]}
        yield client, factory, cfg, headers, effects


def draft(**changes):
    return (
        dict(
            name="Synthetic Drive",
            client_id=CLIENT_ID,
            client_secret=SECRET,
            request_id=str(uuid4()),
            enable_source=True,
            enable_storage=False,
            source_folder_id="root",
        )
        | changes
    )


def create(context, **changes):
    c, _, _, headers, _ = context
    response = c.post(SETUP, json=draft(**changes), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def authorize(context, row):
    c, _, _, headers, _ = context
    response = c.post(
        "/api/integrations/google-drive/" + row["integration_id"] + "/authorize",
        json={"expected_revision": row["revision"], "request_id": str(uuid4())},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    state = parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]
    return state, response.json()["revision"]


def connect(context, **changes):
    c, _, _, _, _ = context
    row = create(context, **changes)
    state, _ = authorize(context, row)
    response = c.get(
        setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False
    )
    assert (
        response.status_code == 303
        and "google_drive_result=connected" in response.headers["location"]
    )
    view = c.get(SETUP, params={"integration_id": row["integration_id"]}).json()
    return view


def test_disabled_optional_setup_has_no_network_and_idempotent_encrypted_secret(context):
    c, factory, cfg, headers, effects = context
    body = draft()
    first = c.post(SETUP, json=body, headers=headers)
    second = c.post(SETUP, json=body, headers=headers)
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    row = first.json()
    assert not row["enabled"] and not row["connected"] and not effects
    assert SECRET not in first.text and "synthetic-access" not in first.text
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert stored.kind == "google_drive" and SECRET not in stored.encrypted_secret
        assert setup.credentials(cfg, stored)["client_secret"] == SECRET
    assert c.post(SETUP, json=body | {"name": "Changed"}, headers=headers).status_code == 409


@pytest.mark.parametrize("source,storage", [(True, False), (False, True), (True, True)])
def test_oauth_binds_exact_capabilities_account_and_single_callback(context, source, storage):
    c, factory, cfg, _, effects = context
    row = create(context, enable_source=source, enable_storage=storage)
    state, revision = authorize(context, row)
    response = c.get(
        setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False
    )
    assert "google_drive_result=connected" in response.headers["location"]
    c.get(setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False)
    assert effects == ["exchange", "about"]
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        data = setup.credentials(cfg, stored)
        assert stored.revision == revision and stored.enabled and stored.writes_enabled is storage
        assert set(data["scope"].split()) == set(drive.scopes(source, storage))
        assert setup.ready(cfg, stored, "source") is source
        assert setup.ready(cfg, stored, "storage") is storage


@pytest.mark.parametrize(
    "case", ["missing_cookie", "expired", "session_revoked", "profile_changed", "network_disabled"]
)
def test_revocation_expiry_and_wrong_session_prevent_exchange(context, case):
    c, factory, cfg, _, effects = context
    row = create(context)
    state, _ = authorize(context, row)
    if case == "missing_cookie":
        c.cookies.clear()
    with factory() as db:
        attempt = db.scalar(
            select(setup.GoogleDriveOAuthAttempt).where(
                setup.GoogleDriveOAuthAttempt.operation == "oauth"
            )
        )
        if case == "expired":
            attempt.expires = time.time() - 1
        if case == "session_revoked":
            db.delete(db.get(LoginSession, attempt.session_hash))
        if case == "profile_changed":
            db.get(Integration, row["integration_id"]).revision += 1
        db.commit()
    if case == "network_disabled":
        object.__setattr__(cfg, "integration_targets_enabled", False)
    response = c.get(
        setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False
    )
    assert "google_drive_result=failed" in response.headers["location"] and not effects


def test_callback_rejects_excess_grant_without_retry(context, monkeypatch):
    c, factory, _, _, effects = context
    row = create(context)
    state, _ = authorize(context, row)

    def wrong(*args, **kwargs):
        effects.append("wrong-exchange")
        return dict(
            access_token="synthetic-access",
            refresh_token="synthetic-refresh",
            expires_at=time.time() + 3600,
            scope=drive.READ_SCOPE + " https://www.googleapis.com/auth/gmail.readonly",
            token_type="Bearer",
        )

    monkeypatch.setattr(drive, "exchange_code", wrong)
    for _ in range(2):
        c.get(
            setup.CALLBACK,
            params={"state": state, "code": "synthetic-code"},
            follow_redirects=False,
        )
    assert effects == ["wrong-exchange"]
    with factory() as db:
        assert not db.get(Integration, row["integration_id"]).enabled
        assert (
            db.scalar(
                select(setup.GoogleDriveOAuthAttempt).where(
                    setup.GoogleDriveOAuthAttempt.operation == "oauth"
                )
            ).status
            == "uncertain"
        )


def test_config_edit_invalidates_credentials_and_cannot_set_existing_storage_folder(context):
    c, factory, cfg, headers, _ = context
    row = connect(context, enable_storage=True)
    response = c.post(
        SETUP,
        json=draft(
            integration_id=row["integration_id"],
            expected_revision=row["revision"],
            source_folder_id="folder_other",
        ),
        headers=headers,
    )
    assert (
        response.status_code == 200
        and not response.json()["connected"]
        and not response.json()["storage_folder_id"]
    )
    assert (
        c.post(SETUP, json=draft(storage_folder_id="arbitrary-folder"), headers=headers).status_code
        == 422
    )
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert not setup.ready(cfg, stored)
        assert "access_token" not in setup.credentials(cfg, stored)


def test_human_off_on_preserves_token_but_revokes_old_operation_revision(context):
    _, factory, cfg, _, _ = context
    row = connect(context, enable_storage=True)
    guard = setup.authority_guard(factory, cfg, row["integration_id"], row["revision"], "storage")
    guard()
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        stored.enabled = False
        stored.revision += 1
        stored.last_check = None
        db.commit()
    with pytest.raises(PermissionError):
        guard()
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        stored.enabled = True
        stored.revision += 1
        revision = stored.revision
        db.commit()
    setup.authority_guard(factory, cfg, row["integration_id"], revision, "storage")()
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        stored.writes_enabled = False
        db.commit()
    with pytest.raises(PermissionError):
        setup.authority_guard(factory, cfg, row["integration_id"], revision, "storage")()


def test_refresh_is_durable_and_failure_disables_instead_of_replaying(context, monkeypatch):
    _, factory, cfg, _, effects = context
    row = connect(context)
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        data = setup.credentials(cfg, stored)
        data["expires_at"] = 0
        setup._store(cfg, stored, data)
        db.commit()

    def fail(*args, **kwargs):
        kwargs["before_send"]()
        effects.append("uncertain-refresh")
        raise TimeoutError()

    monkeypatch.setattr(drive, "refresh_token", fail)
    for _ in range(2):
        with pytest.raises(PermissionError):
            setup.access_token(factory, cfg, row["integration_id"], row["revision"])
    assert effects.count("uncertain-refresh") == 1
    with factory() as db:
        attempt = db.scalar(
            select(setup.GoogleDriveOAuthAttempt).where(
                setup.GoogleDriveOAuthAttempt.operation == "refresh"
            )
        )
        assert (
            attempt.status == "uncertain" and not db.get(Integration, row["integration_id"]).enabled
        )


def test_refresh_updates_only_current_authorized_account_and_secret_not_public(context):
    c, factory, cfg, _, effects = context
    row = connect(context)
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        data = setup.credentials(cfg, stored)
        data["expires_at"] = 0
        setup._store(cfg, stored, data)
        db.commit()
    assert (
        setup.access_token(factory, cfg, row["integration_id"], row["revision"])
        == "synthetic-renewed"
    )
    assert effects.count("refresh") == 1
    assert (
        setup.access_token(factory, cfg, row["integration_id"], row["revision"])
        == "synthetic-renewed"
    )
    assert effects.count("refresh") == 1
    view = c.get(SETUP, params={"integration_id": row["integration_id"]})
    assert "synthetic-renewed" not in view.text and "synthetic-refresh" not in view.text


def test_disconnect_only_clears_local_grants_no_implicit_google_revoke(context):
    c, factory, cfg, headers, effects = context
    row = connect(context, enable_storage=True)
    response = c.post(
        "/api/integrations/google-drive/" + row["integration_id"] + "/disconnect",
        json={"expected_revision": row["revision"]},
        headers=headers,
    )
    assert response.status_code == 200 and not response.json()["connected"]
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert not setup.ready(cfg, stored, "source") and not setup.ready(cfg, stored, "storage")
        assert "refresh_token" not in setup.credentials(cfg, stored)
    assert effects == ["exchange", "about"]


def test_reauthorization_never_reuses_previous_account_storage_folder(context):
    c, factory, cfg, _, _ = context
    row = connect(context, enable_storage=True)
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        config = json.loads(stored.config)
        config["storage_folder_id"] = "synthetic-old-account-folder"
        stored.config = json.dumps(config)
        db.commit()
    old_guard = setup.authority_guard(
        factory, cfg, row["integration_id"], row["revision"], "storage"
    )
    state, _ = authorize(context, row)
    with pytest.raises(PermissionError):
        old_guard()
    current = c.get(SETUP, params={"integration_id": row["integration_id"]}).json()
    assert current["storage_folder_id"] == "" and not current["connected"]
    c.get(setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False)
    assert (
        c.get(SETUP, params={"integration_id": row["integration_id"]}).json()["storage_folder_id"]
        == ""
    )


def test_callback_rechecks_revoked_session_before_account_request(context, monkeypatch):
    c, factory, _, _, effects = context
    row = create(context)
    state, _ = authorize(context, row)

    def exchange(*args, **kwargs):
        kwargs["before_send"]()
        effects.append("exchange")
        with factory() as db:
            attempt = db.scalar(
                select(setup.GoogleDriveOAuthAttempt).where(
                    setup.GoogleDriveOAuthAttempt.operation == "oauth"
                )
            )
            db.delete(db.get(LoginSession, attempt.session_hash))
            db.commit()
        return {
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
            "scope": drive.READ_SCOPE,
            "expires_at": time.time() + 3600,
            "token_type": "Bearer",
        }

    monkeypatch.setattr(drive, "exchange_code", exchange)
    result = c.get(
        setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False
    )
    assert "google_drive_result=failed" in result.headers["location"]
    assert effects == ["exchange"]
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert not stored.enabled and "access_token" not in setup.credentials(context[2], stored)


@pytest.mark.parametrize("damage", ["corrupt_cipher", "wrong_aad", "invalid_json", "wrong_key"])
def test_unreadable_credentials_fail_closed_without_breaking_registry(context, monkeypatch, damage):
    from hub.provider_settings import encrypt

    client, factory, cfg, _, effects = context
    view = connect(context, enable_storage=True)
    with factory() as db:
        row = db.get(Integration, view["integration_id"])
        if damage == "corrupt_cipher":
            raw = bytearray(base64.b64decode(row.encrypted_secret))
            raw[-1] ^= 1
            row.encrypted_secret = base64.b64encode(raw).decode()
        elif damage == "wrong_aad":
            row.encrypted_secret = encrypt(
                cfg, "integration:another-account", '{"secret":"synthetic-private-value"}'
            )
        elif damage == "invalid_json":
            row.encrypted_secret = encrypt(
                cfg, "integration:" + row.id, "not valid credential json"
            )
        db.commit()
        before = (row.revision, row.enabled, row.writes_enabled, row.config, row.encrypted_secret)
    if damage == "wrong_key":
        from pathlib import Path

        Path(cfg.secrets_key_file).write_text(base64.b64encode(b"x" * 32).decode())

    def forbidden(*args, **kwargs):
        pytest.fail("Unreadable Drive credentials must not contact Google")

    monkeypatch.setattr(drive, "client", forbidden)
    with factory() as db:
        row = db.get(Integration, view["integration_id"])
        assert not setup.ready(cfg, row, "source") and not setup.ready(cfg, row, "storage")
        with pytest.raises(ValueError, match="Google Drive credentials unavailable"):
            setup.credentials(cfg, row)
    result = client.get("/api/integrations")
    assert result.status_code == 200
    registry = next(
        row for row in result.json()["integrations"] if row["id"] == view["integration_id"]
    )
    assert registry["availability_reason"] == "credential_missing"
    for url in [
        SETUP + "?integration_id=" + view["integration_id"],
        "/api/integrations/google-drive/" + view["integration_id"] + "/status",
    ]:
        result = client.get(url)
        assert (
            result.status_code == 503 and "Serververschlüsselung prüfen" in result.json()["detail"]
        )
        assert all(
            secret not in result.text
            for secret in [SECRET, "synthetic-private-value", before[-1], "InvalidTag"]
        )
    with factory() as db:
        row = db.get(Integration, view["integration_id"])
        assert (
            row.revision,
            row.enabled,
            row.writes_enabled,
            row.config,
            row.encrypted_secret,
        ) == before
    assert effects == ["exchange", "about"]
