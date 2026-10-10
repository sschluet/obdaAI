import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
import test_chat
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import verify_password
from hub.config import Settings
from hub.db import AccountCredential, LoginSession, LoginThrottle
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


OLD = "synthetic-test-password"
NEW = "synthetic-new-password-2026"


def body(**overrides):
    return {"current_password": OLD, "new_password": NEW, "confirm_password": NEW, **overrides}


def test_password_change_persists_over_bootstrap_and_revokes_every_session(setup):
    app, client, headers, _ = setup
    with TestClient(create_app(app.state.settings)) as other:
        assert (
            other.post(
                "/api/login", json={"password": OLD}, headers={"Origin": app.state.settings.origin}
            ).status_code
            == 200
        )
        response = client.post("/api/account/password", json=body(), headers=headers)
        assert response.status_code == 200
        assert response.json() == {"changed": True, "reauthenticate": True}
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert NEW not in response.text and OLD not in response.text
        assert client.get("/api/me").status_code == 401
        assert other.get("/api/me").status_code == 401
    with app.state.sessions() as db:
        credential = db.get(AccountCredential, 1)
        assert credential.revision == 1 and credential.changed
        assert credential.password_hash != NEW
        assert verify_password(NEW, credential.password_hash)
        assert db.scalar(select(func.count()).select_from(LoginSession)) == 0
    # A separate app with the original environment hash must use the durable hash.
    with TestClient(create_app(app.state.settings)) as restarted:
        assert (
            restarted.post(
                "/api/login", json={"password": OLD}, headers={"Origin": app.state.settings.origin}
            ).status_code
            == 401
        )
        assert (
            restarted.post(
                "/api/login", json={"password": NEW}, headers={"Origin": app.state.settings.origin}
            ).status_code
            == 200
        )
    with TestClient(create_app(replace(app.state.settings, password_hash=""))) as no_bootstrap:
        assert (
            no_bootstrap.post(
                "/api/login",
                json={"password": NEW},
                headers={"Origin": app.state.settings.origin},
            ).status_code
            == 200
        )


@pytest.mark.parametrize(
    "overrides,status",
    [
        ({"current_password": "synthetic-wrong-password"}, 401),
        ({"confirm_password": "synthetic-different-password"}, 422),
        ({"new_password": "short", "confirm_password": "short"}, 422),
        ({"new_password": OLD, "confirm_password": OLD}, 422),
        ({"new_password": "x" * 257}, 422),
    ],
)
def test_invalid_change_preserves_login_and_does_not_echo_secrets(setup, overrides, status):
    app, client, headers, _ = setup
    response = client.post("/api/account/password", json=body(**overrides), headers=headers)
    assert response.status_code == status
    for value in body(**overrides).values():
        assert value not in response.text
    assert client.get("/api/me").status_code == 200
    with app.state.sessions() as db:
        assert db.get(AccountCredential, 1).password_hash is None


def test_login_in_flight_is_serialized_before_change_then_revoked(setup, monkeypatch):
    assert_login_change_serialization(setup, monkeypatch)


def assert_login_change_serialization(setup, monkeypatch):
    app, client, headers, _ = setup
    import hub.account_api as account
    import hub.api as api

    original_verify = api.verify_password
    original_attempt = account.consume_auth_attempt
    login_locked, change_started, resume = (threading.Event() for _ in range(3))

    def pause_verify(password, stored):
        login_locked.set()
        assert resume.wait(5)
        return original_verify(password, stored)

    def observe_change(factory, bucket, now):
        change_started.set()
        return original_attempt(factory, bucket, now)

    monkeypatch.setattr(api, "verify_password", pause_verify)
    monkeypatch.setattr(account, "consume_auth_attempt", observe_change)
    with TestClient(create_app(app.state.settings)) as other:
        with ThreadPoolExecutor(max_workers=2) as pool:
            login = pool.submit(
                other.post,
                "/api/login",
                json={"password": OLD},
                headers={"Origin": app.state.settings.origin},
            )
            assert login_locked.wait(5)
            change = pool.submit(client.post, "/api/account/password", json=body(), headers=headers)
            assert change_started.wait(5)
            assert not change.done()
            resume.set()
            assert login.result().status_code == 200
            assert change.result().status_code == 200
        assert other.get("/api/me").status_code == 401
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(LoginSession)) == 0


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PostgreSQL required")
def test_postgres_two_api_credentials_serialize_login_and_change(monkeypatch):
    from hub.auth import password_hash

    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Refusing any database except the loopback hub_ci fixture")
    schema = "account_test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA " + schema)
    isolated = parsed.update_query_dict({"options": "-csearch_path=" + schema})
    cfg = Settings(
        database_url=isolated.render_as_string(hide_password=False),
        origin="http://testserver",
        secure_cookie=False,
        password_hash=password_hash(OLD),
    )
    app = create_app(cfg)
    try:
        engine = app.state.sessions.kw["bind"]
        for model in (AccountCredential, LoginSession, LoginThrottle):
            model.__table__.create(engine)
        with app.state.sessions() as db:
            db.add(AccountCredential(id=1, revision=0))
            db.add_all([LoginThrottle(id=b, window=0, attempts=0) for b in (1, 2)])
            db.commit()
        with TestClient(app) as client:
            login = client.post(
                "/api/login", json={"password": OLD}, headers={"Origin": cfg.origin}
            )
            assert login.status_code == 200
            headers = {"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]}
            assert_login_change_serialization((app, client, headers, None), monkeypatch)
    finally:
        app.state.sessions.kw["bind"].dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA " + schema + " CASCADE")
        admin.dispose()


def test_password_change_requires_session_origin_and_csrf(setup):
    app, client, headers, _ = setup
    for altered in [
        {},
        {**headers, "Origin": "https://example.org"},
        {**headers, "X-CSRF-Token": "wrong"},
    ]:
        assert client.post("/api/account/password", json=body(), headers=altered).status_code == 403
    client.cookies.clear()
    assert client.post("/api/account/password", json=body(), headers=headers).status_code == 401


def test_password_confirmation_attempts_are_durable_and_independent_of_login(setup):
    app, client, headers, _ = setup
    for _ in range(5):
        assert (
            client.post(
                "/api/account/password", json=body(current_password="wrong"), headers=headers
            ).status_code
            == 401
        )
    assert client.post("/api/account/password", json=body(), headers=headers).status_code == 429
    with TestClient(create_app(app.state.settings)) as other:
        login = other.post(
            "/api/login", json={"password": OLD}, headers={"Origin": app.state.settings.origin}
        )
        assert login.status_code == 200
        assert (
            other.post(
                "/api/account/password",
                json=body(),
                headers={**headers, "X-CSRF-Token": login.json()["csrf"]},
            ).status_code
            == 429
        )
    with app.state.sessions() as db:
        throttle = db.get(LoginThrottle, 2)
        throttle.window = 0
        db.commit()
    assert client.post("/api/account/password", json=body(), headers=headers).status_code == 200


def test_session_invalidated_between_auth_dependency_and_transaction_cannot_change(
    setup, monkeypatch
):
    app, client, headers, _ = setup
    import hub.account_api as account

    original = account.consume_auth_attempt
    reached = threading.Event()
    resume = threading.Event()

    def pause(factory, bucket, now):
        original(factory, bucket, now)
        reached.set()
        assert resume.wait(5)

    monkeypatch.setattr(account, "consume_auth_attempt", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(client.post, "/api/account/password", json=body(), headers=headers)
        assert reached.wait(5)
        with app.state.sessions() as db:
            for session in db.scalars(select(LoginSession)):
                db.delete(session)
            db.commit()
        resume.set()
        assert request.result().status_code == 401
    with app.state.sessions() as db:
        assert db.get(AccountCredential, 1).password_hash is None


def test_password_migration_cannot_discard_changed_credential(setup):
    from alembic import command
    from alembic.config import Config

    app, client, headers, _ = setup
    assert client.post("/api/account/password", json=body(), headers=headers).status_code == 200
    with pytest.raises(RuntimeError, match="Preserve the configured login credential"):
        command.downgrade(Config("alembic.ini"), "0025")
    with app.state.sessions() as db:
        assert verify_password(NEW, db.get(AccountCredential, 1).password_hash)
