"""OAuth session binding, least authority, one-shot callbacks and renewal evidence."""

import base64
import json
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub import gmail_setup as setup
from hub.agent_models import AgentPolicy
from hub.api import create_app
from hub.auth import password_hash, token_hash
from hub.config import Settings
from hub.db import LoginSession, session_factory
from hub.gmail_client import SCOPE
from hub.integrations import Integration
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

SETUP = "/api/integrations/gmail/setup"
CLIENT_ID = "synthetic-google-client.apps.googleusercontent.com"
SECRET = "synthetic-client-secret-not-a-real-account"


@pytest.fixture
def gmail(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_text(base64.b64encode(b"k" * 32).decode())
    key.chmod(0o600)
    cfg = Settings(
        database_url="sqlite:///" + str(tmp_path / "gmail.sqlite"),
        origin="http://127.0.0.1:18765",
        secure_cookie=False,
        password_hash=password_hash("synthetic-password"),
        secrets_key_file=str(key),
        integration_targets_enabled=True,
    )
    monkeypatch.setenv("HUB_DATABASE_URL", cfg.database_url)
    command.upgrade(Config("alembic.ini"), "head")
    app = create_app(cfg)
    factory = session_factory(cfg.database_url)
    effects = []

    def exchange(client_id, client_secret, redirect_uri, code, verifier, *, before_send):
        before_send()
        effects.append(("exchange", code, verifier))
        with factory() as db:
            intent = db.scalar(
                select(setup.GmailOAuthAttempt).where(
                    setup.GmailOAuthAttempt.operation == "oauth",
                    setup.GmailOAuthAttempt.status == "dispatching",
                )
            )
            assert intent and intent.encrypted_verifier is None
            row = db.get(Integration, intent.integration_id)
            assert not row.enabled and not row.writes_enabled
        return dict(
            access_token="synthetic-access",
            refresh_token="synthetic-refresh",
            expires_at=time.time() + 3600,
            scope=SCOPE,
            token_type="Bearer",
        )

    monkeypatch.setattr(setup.gmail_client, "exchange_code", exchange)

    class Client:
        def __init__(self, token, *, before_send):
            self.before_send = before_send

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def profile(self):
            self.before_send()
            effects.append(("profile",))
            return {"emailAddress": "aurora@example.test"}

    monkeypatch.setattr(setup.gmail_client, "GmailClient", Client)

    def refresh(client_id, client_secret, refresh_token, *, before_send):
        before_send()
        effects.append(("refresh",))
        return dict(
            access_token="synthetic-renewed-access",
            refresh_token="",
            expires_at=time.time() + 3600,
            scope=SCOPE,
            token_type="Bearer",
        )

    monkeypatch.setattr(setup.gmail_client, "refresh_token", refresh)
    with TestClient(app, base_url=cfg.origin) as client:
        login = client.post(
            "/api/login", json={"password": "synthetic-password"}, headers={"Origin": cfg.origin}
        )
        assert login.status_code == 200, login.text
        headers = {"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]}
        yield client, factory, cfg, headers, effects


def draft(**changes):
    return (
        dict(
            name="Gmail Aurora",
            client_id=CLIENT_ID,
            client_secret=SECRET,
            request_id=str(uuid4()),
            enable_reads=True,
        )
        | changes
    )


def create(gmail, **changes):
    c, factory, cfg, headers, effects = gmail
    response = c.post(SETUP, json=draft(**changes), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def authorize(gmail, row):
    c, factory, cfg, headers, effects = gmail
    response = c.post(
        f"/api/integrations/gmail/{row['integration_id']}/authorize",
        json={"expected_revision": row["revision"], "request_id": str(uuid4())},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    value = response.json()
    params = parse_qs(urlsplit(value["authorization_url"]).query)
    return value, params["state"][0]


def connect(gmail, **changes):
    c, factory, cfg, headers, effects = gmail
    row = create(gmail, **changes)
    authorization, state = authorize(gmail, row)
    callback = c.get(
        setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False
    )
    assert (
        callback.status_code == 303 and "gmail_result=connected" in callback.headers["location"]
    ), callback.text
    return c.get(f"/api/integrations/gmail/{row['integration_id']}/status").json()


def test_setup_auth_csrf_secret_blank_revision_and_dedup(gmail):
    c, factory, cfg, h, effects = gmail
    assert c.post(SETUP, json=draft()).status_code == 403
    body = draft()
    first = c.post(SETUP, json=body, headers=h)
    assert first.status_code == 200, first.text
    row = first.json()
    assert not row["connected"] and not row["enabled"] and row["configured"]
    assert SECRET not in first.text and row["client_secret_saved"]
    assert c.post(SETUP, json=body, headers=h).json()["integration_id"] == row["integration_id"]
    update = {
        **draft(),
        "integration_id": row["integration_id"],
        "expected_revision": row["revision"],
        "client_secret": None,
    }
    result = c.post(SETUP, json=update, headers=h)
    assert result.status_code == 200 and result.json()["revision"] == 2
    changed = {
        **update,
        "request_id": str(uuid4()),
        "expected_revision": 2,
        "client_id": "other-client.apps.googleusercontent.com",
    }
    assert c.post(SETUP, json=changed, headers=h).status_code == 422
    assert not effects
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert SECRET not in stored.config + stored.encrypted_secret
        assert setup.credentials(cfg, stored) == {"client_id": CLIENT_ID, "client_secret": SECRET}


def test_callback_pkce_cookie_original_session_and_scope_policy(gmail):
    c, factory, cfg, h, effects = gmail
    row = create(gmail)
    response, state = authorize(gmail, row)
    params = parse_qs(urlsplit(response["authorization_url"]).query)
    assert params["scope"] == [SCOPE] and params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == [cfg.origin + setup.CALLBACK]
    assert response["revision"] == row["revision"] + 1
    cookie = next(v for v in c.cookies.jar if v.name == setup.COOKIE)
    assert cookie.path == setup.CALLBACK and "HttpOnly" in cookie._rest
    # Google's cross-site navigation withholds the ordinary Strict session cookie.
    c.cookies.delete("hub_session")
    result = c.get(
        setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False
    )
    assert "gmail_result=connected" in result.headers["location"]
    assert (
        "synthetic-code" not in result.headers["location"]
        and state not in result.headers["location"]
    )
    assert (
        "gmail_integration=" + row["integration_id"]
        in urlsplit(result.headers["location"]).fragment
    )
    assert setup.COOKIE not in c.cookies
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert setup.read_ready(cfg, stored)
        assert json.loads(stored.config)["account_email"] == "aurora@example.test"
        assert "oauth_pending_until" not in json.loads(stored.config)
        policy = db.get(AgentPolicy, stored.id)
        rules = json.loads(policy.rules)
        assert rules["enabled"] and rules["gmail_read"] and rules["private_data_to_target"]
        assert not stored.writes_enabled and not rules["autonomous"] and rules["max_effects"] == 0
        assert not rules["mcp"] and not rules["shell"] and not rules["file_upload"]
        attempt = db.scalar(
            select(setup.GmailOAuthAttempt).where(setup.GmailOAuthAttempt.operation == "oauth")
        )
        assert attempt.status == "succeeded" and attempt.encrypted_verifier is None
        assert state not in attempt.state_hash and state not in attempt.cookie_hash
    assert len(effects) == 2
    replay = c.get(
        setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False
    )
    assert "gmail_result=failed" in replay.headers["location"] and len(effects) == 2


def test_read_consent_false_preserves_connected_but_policy_off(gmail):
    row = connect(gmail, enable_reads=False)
    c, factory, cfg, h, effects = gmail
    assert row["connected"] and row["enabled"] and not row["enable_reads"]
    with factory() as db:
        policy = db.get(AgentPolicy, row["integration_id"])
        rules = json.loads(policy.rules)
        assert (
            not rules["enabled"] and not rules["gmail_read"] and not rules["private_data_to_target"]
        )


@pytest.mark.parametrize(
    "failure", ["other_session", "expired", "revoked_session", "revision", "denied"]
)
def test_callback_rejects_stale_or_unbound_authority(gmail, failure):
    c, factory, cfg, h, effects = gmail
    row = create(gmail)
    authorization, state = authorize(gmail, row)
    with factory() as db:
        attempt = db.scalar(
            select(setup.GmailOAuthAttempt).where(setup.GmailOAuthAttempt.operation == "oauth")
        )
        if failure == "expired":
            attempt.expires = 0
        if failure == "revoked_session":
            db.delete(db.get(LoginSession, attempt.session_hash))
        if failure == "revision":
            db.get(Integration, row["integration_id"]).revision += 1
        db.commit()
    if failure == "other_session":
        c.cookies.clear()
        raw = "synthetic-other-browser-session"
        with factory() as db:
            db.add(
                LoginSession(
                    token_hash=token_hash(raw),
                    csrf="synthetic-other-csrf",
                    expires=time.time() + 600,
                )
            )
            db.commit()
        c.cookies.set("hub_session", raw)
    query = {"state": state, "code": "synthetic-code"}
    if failure == "denied":
        query = {"state": state, "error": "access_denied"}
    result = c.get(setup.CALLBACK, params=query, follow_redirects=False)
    assert "gmail_result=failed" in result.headers["location"] and not effects
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert not stored.enabled
        if failure in {"expired", "denied", "revoked_session"}:
            assert "oauth_pending_until" not in json.loads(stored.config)


def test_exchange_failure_terminal_no_automatic_retry(gmail, monkeypatch):
    c, factory, cfg, h, effects = gmail
    row = create(gmail)
    authorization, state = authorize(gmail, row)

    def fail(*args, **kwargs):
        kwargs["before_send"]()
        effects.append(("exchange_failed",))
        raise TimeoutError("never echo synthetic secret")

    monkeypatch.setattr(setup.gmail_client, "exchange_code", fail)
    for _ in range(2):
        result = c.get(
            setup.CALLBACK,
            params={"state": state, "code": "synthetic-code"},
            follow_redirects=False,
        )
        assert (
            "gmail_result=failed" in result.headers["location"]
            and "synthetic secret" not in result.text
        )
    assert len(effects) == 1
    with factory() as db:
        attempt = db.scalar(
            select(setup.GmailOAuthAttempt).where(setup.GmailOAuthAttempt.operation == "oauth")
        )
        assert attempt.status == "uncertain" and attempt.encrypted_verifier is None
        assert "oauth_pending_until" not in json.loads(
            db.get(Integration, row["integration_id"]).config
        )


def test_local_disconnect_revokes_authority_and_erases_tokens(gmail, monkeypatch):
    row = connect(gmail)
    c, factory, cfg, h, effects = gmail
    monkeypatch.setattr(
        setup.gmail_client,
        "revoke_token",
        lambda *a, **k: pytest.fail("Local disconnect must not contact Google"),
    )
    path = f"/api/integrations/gmail/{row['integration_id']}/disconnect"
    assert (
        c.post(
            path, json={"expected_revision": row["revision"], "revoke_google": True}, headers=h
        ).status_code
        == 422
    )
    result = c.post(path, json={"expected_revision": row["revision"]}, headers=h)
    assert (
        result.status_code == 200
        and not result.json()["connected"]
        and not result.json()["enabled"]
    )
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert not setup.read_ready(cfg, stored)
        assert set(setup.credentials(cfg, stored)) == {"client_id", "client_secret"}
        assert stored.revision == row["revision"] + 1
    assert c.post(path, json={"expected_revision": row["revision"]}, headers=h).status_code == 409


def test_refresh_once_with_committing_runtime_gate(gmail):
    row = connect(gmail)
    c, factory, cfg, h, effects = gmail
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        old = setup.credentials(cfg, stored)
        old["expires_at"] = 0
        setup._store(cfg, stored, old)
        db.commit()
        revision = stored.revision
        calls = []

        def committing_gate():
            calls.append("gate")
            db.commit()

        data = setup.refresh_credentials(db, cfg, stored, committing_gate)
        assert (
            data["access_token"] == "synthetic-renewed-access"
            and data["refresh_token"] == "synthetic-refresh"
        )
        assert stored.revision == revision and len(calls) >= 3
        assert len([effect for effect in effects if effect[0] == "refresh"]) == 1
        setup.refresh_credentials(db, cfg, stored, committing_gate)
        assert len([effect for effect in effects if effect[0] == "refresh"]) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(setup.GmailOAuthAttempt)
                .where(setup.GmailOAuthAttempt.operation == "refresh")
            )
            == 1
        )


def test_expired_refresh_tombstone_requires_reconnect_live_intent_is_busy(gmail):
    row = connect(gmail)
    c, factory, cfg, h, effects = gmail
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        revision = stored.revision
        pending = setup.GmailOAuthAttempt(
            request_id=str(uuid4()),
            request_digest="d" * 64,
            operation="refresh",
            integration_id=stored.id,
            profile_revision=revision,
            session_hash="",
            status="dispatching",
            expires=time.time() + 90,
        )
        db.add(pending)
        db.commit()
        with pytest.raises(PermissionError, match="in progress"):
            setup.refresh_credentials(db, cfg, stored, lambda: db.commit())
        assert stored.enabled and stored.revision == revision
        pending.expires = 0
        db.commit()
        with pytest.raises(PermissionError, match="reconnection"):
            setup.refresh_credentials(db, cfg, stored, lambda: db.commit())
        assert not stored.enabled and stored.revision == revision + 1 and not stored.last_check
        assert json.loads(stored.config)["reauthorization_required"]
        assert pending.status == "dispatching"
    assert not [effect for effect in effects if effect[0] == "refresh"]


def test_database_enforces_one_active_refresh(gmail):
    row = connect(gmail)
    c, factory, cfg, h, effects = gmail
    with factory() as db:

        def intent():
            return setup.GmailOAuthAttempt(
                request_id=str(uuid4()),
                request_digest="d" * 64,
                operation="refresh",
                integration_id=row["integration_id"],
                profile_revision=row["revision"],
                session_hash="",
                status="dispatching",
                expires=time.time() + 90,
            )

        db.add(intent())
        db.commit()
        db.add(intent())
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_no_auth_bypass_and_no_validation_secret_echo(gmail):
    c, factory, cfg, headers, effects = gmail
    row = create(gmail)
    authorization, state = authorize(gmail, row)
    c.cookies.delete("hub_session")
    assert c.get(SETUP).status_code == 401
    assert c.post(SETUP, json=draft(), headers=headers).status_code == 401
    # The scoped continuation cookie can only complete its own authorized flow.
    assert setup.COOKIE in c.cookies
    failed = c.get(
        setup.CALLBACK,
        params={"state": "wrong-state-" + state, "code": "synthetic-code"},
        follow_redirects=False,
    )
    assert failed.status_code == 303 and not effects
    assert failed.headers["Cache-Control"] == "no-store"
    assert failed.headers["Referrer-Policy"] == "no-referrer"
    assert setup.COOKIE not in c.cookies


@pytest.mark.parametrize(
    "key,value",
    [("scope", "https://mail.google.com/"), ("refresh_token", ""), ("token_type", "Other")],
)
def test_callback_rejects_incomplete_or_broader_tokens(gmail, monkeypatch, key, value):
    c, factory, cfg, headers, effects = gmail
    row = create(gmail)
    authorization, state = authorize(gmail, row)
    exchange = setup.gmail_client.exchange_code

    def invalid(*args, **kwargs):
        data = exchange(*args, **kwargs)
        data[key] = value
        return data

    monkeypatch.setattr(setup.gmail_client, "exchange_code", invalid)
    result = c.get(
        setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False
    )
    assert "gmail_result=failed" in result.headers["location"]
    assert not any(effect[0] == "profile" for effect in effects)
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert not stored.enabled
        assert set(setup.credentials(cfg, stored)) == {"client_id", "client_secret"}


def test_revision_change_during_exchange_blocks_profile_and_credential_save(gmail, monkeypatch):
    c, factory, cfg, h, effects = gmail
    row = create(gmail)
    authorization, state = authorize(gmail, row)
    exchange = setup.gmail_client.exchange_code

    def revoked(*args, **kwargs):
        data = exchange(*args, **kwargs)
        with factory() as db:
            profile = db.get(Integration, row["integration_id"])
            profile.revision += 1
            db.commit()
        return data

    monkeypatch.setattr(setup.gmail_client, "exchange_code", revoked)
    result = c.get(
        setup.CALLBACK, params={"state": state, "code": "synthetic-code"}, follow_redirects=False
    )
    assert "gmail_result=failed" in result.headers["location"]
    assert not any(effect[0] == "profile" for effect in effects)
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        assert not stored.enabled
        assert not setup.credentials(cfg, stored).get("access_token")


def test_refresh_transport_uncertainty_is_durable_and_requires_reconnect(gmail, monkeypatch):
    row = connect(gmail)
    c, factory, cfg, h, effects = gmail
    calls = []

    def fail(*args, **kwargs):
        kwargs["before_send"]()
        calls.append("HTTP")
        raise TimeoutError("synthetic token never returned")

    monkeypatch.setattr(setup.gmail_client, "refresh_token", fail)
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        data = setup.credentials(cfg, stored)
        data["expires_at"] = 0
        setup._store(cfg, stored, data)
        db.commit()
        with pytest.raises(PermissionError, match="renewal failed"):
            setup.refresh_credentials(db, cfg, stored, lambda: db.commit())
        assert not stored.enabled and json.loads(stored.config)["reauthorization_required"]
        attempt = db.scalar(
            select(setup.GmailOAuthAttempt).where(setup.GmailOAuthAttempt.operation == "refresh")
        )
        assert attempt.status == "uncertain"
        with pytest.raises(PermissionError):
            setup.refresh_credentials(db, cfg, stored, lambda: db.commit())
    assert calls == ["HTTP"]


def test_concurrent_reader_does_not_duplicate_or_cancel_inflight_refresh(gmail, monkeypatch):
    import concurrent.futures
    import threading

    row = connect(gmail)
    c, factory, cfg, h, effects = gmail
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        data = setup.credentials(cfg, stored)
        data["expires_at"] = 0
        setup._store(cfg, stored, data)
        db.commit()
    started, release = threading.Event(), threading.Event()
    original = setup.gmail_client.refresh_token

    def slow(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(setup.gmail_client, "refresh_token", slow)

    def first():
        with factory() as db:
            profile = db.get(Integration, row["integration_id"])
            return setup.refresh_credentials(db, cfg, profile, lambda: db.commit())

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(first)
        try:
            assert started.wait(5)
            with factory() as db:
                profile = db.get(Integration, row["integration_id"])
                with pytest.raises(PermissionError, match="in progress"):
                    setup.refresh_credentials(db, cfg, profile, lambda: db.commit())
                assert profile.enabled and profile.revision == row["revision"]
        finally:
            release.set()
        assert pending.result(timeout=5)["access_token"] == "synthetic-renewed-access"
    assert len([effect for effect in effects if effect[0] == "refresh"]) == 1


def test_authorize_idempotency_stale_revision_and_pending_expiry(gmail):
    c, factory, cfg, h, effects = gmail
    row = create(gmail)
    path = f"/api/integrations/gmail/{row['integration_id']}/authorize"
    body = {"request_id": str(uuid4()), "expected_revision": row["revision"]}
    first = c.post(path, json=body, headers=h)
    assert first.status_code == 200
    second = c.post(path, json=body, headers=h)
    assert second.status_code == 200 and first.json() == second.json()
    with factory() as db:
        stored = db.get(Integration, row["integration_id"])
        config = json.loads(stored.config)
        assert not stored.enabled and config["oauth_pending_until"] > time.time()
        assert stored.revision == row["revision"] + 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(setup.GmailOAuthAttempt)
                .where(setup.GmailOAuthAttempt.operation == "oauth")
            )
            == 1
        )
    assert c.post(path, json={**body, "request_id": str(uuid4())}, headers=h).status_code == 409
    assert not effects


def test_secret_validation_errors_never_echo_credentials(gmail):
    c, factory, cfg, h, effects = gmail
    for changes in [{"client_id": "invalid"}, {"enable_reads": "true"}, {"extra": "forbidden"}]:
        result = c.post(SETUP, json=draft(**changes), headers=h)
        assert result.status_code == 422 and SECRET not in result.text
    assert not effects
