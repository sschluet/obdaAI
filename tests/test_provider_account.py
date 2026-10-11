import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from hub.db import BudgetReservation, ProviderConfig
from hub.provider_account import money

pytest_plugins = ["test_chat"]


@pytest.fixture
def account(setup, tmp_path):
    app, client, headers, _ = setup
    from hub.provider_settings import seed

    with app.state.sessions() as db:
        seed(db, app.state.settings)
        row = db.get(ProviderConfig, "openrouter-default")
        row.enabled = True
        data = json.loads(row.config)
        data.update(monthly_budget=10, max_run_cost=1)
        row.config = json.dumps(data)
        db.commit()
    # Existing fixture has no real key; stub only credential file reads.
    return app, client, headers


def test_get_auth_no_network_and_persistent_ledger(account, monkeypatch):
    app, client, headers = account

    async def forbidden(*args):
        raise AssertionError("GET must not call external API")

    monkeypatch.setattr("hub.provider_account.fetch_metadata", forbidden)
    now = datetime.now(UTC)
    with app.state.sessions() as db:
        db.add_all(
            [
                BudgetReservation(
                    id="deleted-run",
                    provider_id="openrouter-default",
                    month=now.strftime("%Y-%m"),
                    measured=0.12,
                    ceiling=0.4,
                ),
                BudgetReservation(
                    id="unknown",
                    provider_id="openrouter-default",
                    month=now.strftime("%Y-%m"),
                    measured=None,
                    ceiling=0.3,
                ),
            ]
        )
        db.commit()
    result = client.get("/api/providers/openrouter-default/account-status").json()
    assert result["account"] is None and result["key"] is None
    assert result["local"]["month_used"] == "0.42"
    assert result["local"]["month_reserved"] == "0.3"
    assert result["local"]["month_unknown_count"] == 1
    assert (
        client.post("/api/providers/openrouter-default/account-status/refresh").status_code == 403
    )
    client.cookies.clear()
    assert client.get("/api/providers/openrouter-default/account-status").status_code == 401


def allow_key(app, monkeypatch):
    # Simulate an existing encrypted inference key, never a management secret.
    with app.state.sessions() as db:
        row = db.get(ProviderConfig, "openrouter-default")
        row.encrypted_secret = "synthetic-encrypted"
        db.commit()
    monkeypatch.setattr("hub.provider_account.decrypt", lambda *args: "SYNTHETIC_SECRET")


def test_refresh_regular_key_partial_cache_and_revision(account, monkeypatch):
    app, client, headers = account
    allow_key(app, monkeypatch)
    calls = []

    async def fetch(key, path):
        calls.append(path)
        assert key == "SYNTHETIC_SECRET"
        if path == "/credits":
            response = httpx.Response(403, request=httpx.Request("GET", "https://openrouter.ai"))
            raise httpx.HTTPStatusError(
                "SENSITIVE ERROR", request=response.request, response=response
            )
        return {
            "usage": 0.8,
            "usage_daily": 0.1,
            "limit": None,
            "limit_remaining": None,
            "label": "SENSITIVE_LABEL",
            "is_free_tier": False,
        }

    monkeypatch.setattr("hub.provider_account.fetch_metadata", fetch)
    url = "/api/providers/openrouter-default/account-status"
    result = client.post(url + "/refresh", headers=headers)
    assert result.status_code == 200
    data = result.json()
    assert data["state"] == "ready" and data["account"] is None
    assert data["key"]["limit_remaining"] is None and data["key"]["usage"] == "0.8"
    assert data["account_error"]
    assert "SENSITIVE" not in result.text and "SYNTHETIC_SECRET" not in result.text
    client.post(url + "/refresh", headers=headers).raise_for_status()
    assert calls == ["/key"]
    with app.state.sessions() as db:
        row = db.get(ProviderConfig, "openrouter-default")
        row.revision += 1
        db.commit()
    assert client.get(url).json()["key"] is None
    client.post(url + "/refresh", headers=headers).raise_for_status()
    assert len(calls) == 2


def test_full_balance_and_no_budget_mutation(account, monkeypatch):
    app, client, headers = account
    allow_key(app, monkeypatch)
    from hub.db import ProviderAccountCredential

    with app.state.sessions() as db:
        db.add(
            ProviderAccountCredential(
                provider_id="openrouter-default",
                revision=1,
                encrypted_secret="synthetic-management",
            )
        )
        db.commit()

    async def fetch(key, path):
        return (
            {"usage": 2, "limit": None, "limit_remaining": None}
            if path == "/key"
            else {"total_credits": 10, "total_usage": 2.5}
        )

    monkeypatch.setattr("hub.provider_account.fetch_metadata", fetch)
    result = client.post(
        "/api/providers/openrouter-default/account-status/refresh", headers=headers
    )
    assert result.json()["account"]["balance"] == "7.5"
    with app.state.sessions() as db:
        assert (
            json.loads(db.get(ProviderConfig, "openrouter-default").config)["monthly_budget"] == 10
        )
        assert db.query(BudgetReservation).count() == 0


@pytest.mark.parametrize("bad", [True, "NaN", "Infinity", -1, {}, 1e30])
def test_money_validation(bad):
    with pytest.raises(ValueError):
        money(bad)


def test_invalid_metadata_sanitized(account, monkeypatch):
    app, client, headers = account
    allow_key(app, monkeypatch)

    async def fetch(key, path):
        return {"usage": "NaN", "label": "DO_NOT_ECHO"}

    monkeypatch.setattr("hub.provider_account.fetch_metadata", fetch)
    result = client.post(
        "/api/providers/openrouter-default/account-status/refresh", headers=headers
    )
    assert result.json()["state"] == "error" and result.json()["key"] is None
    assert "DO_NOT_ECHO" not in result.text


def test_provider_gate_and_drift(account, monkeypatch):
    app, client, headers = account
    allow_key(app, monkeypatch)

    async def fetch(key, path):
        with app.state.sessions() as db:
            row = db.get(ProviderConfig, "openrouter-default")
            row.revision += 1
            db.commit()
        return {
            "usage": 0,
            "limit": None,
            "limit_remaining": None,
            "total_credits": 10,
            "total_usage": 0,
        }

    monkeypatch.setattr("hub.provider_account.fetch_metadata", fetch)
    url = "/api/providers/openrouter-default/account-status"
    assert client.post(url + "/refresh", headers=headers).status_code == 409
    assert client.get(url).json()["account"] is None
    with app.state.sessions() as db:
        db.get(ProviderConfig, "openrouter-default").enabled = False
        db.commit()
    assert client.post(url + "/refresh", headers=headers).status_code == 409


def test_separate_credential_cas_encryption_and_clear(account, monkeypatch):
    app, client, headers = account
    allow_key(app, monkeypatch)
    monkeypatch.setattr(
        "hub.provider_account.encrypt", lambda cfg, context, key: context + ":ENCRYPTED"
    )
    url = "/api/providers/openrouter-default/account-status"
    original = client.get(url).json()
    body = {
        "expected_revision": original["revision"],
        "expected_credentials_revision": 0,
        "api_key": "PRIVATE_MANAGEMENT_SECRET",
    }
    result = client.put(url + "/credentials", headers=headers, json=body)
    assert result.status_code == 200
    assert result.json()["revision"] == original["revision"]
    assert result.json()["credentials_revision"] == 1
    assert result.json()["account_key_configured"]
    assert "PRIVATE_MANAGEMENT_SECRET" not in result.text
    assert client.put(url + "/credentials", headers=headers, json=body).status_code == 409
    assert client.put(url + "/credentials", json=body).status_code == 403
    with app.state.sessions() as db:
        assert (
            db.get(ProviderConfig, "openrouter-default").encrypted_secret == "synthetic-encrypted"
        )
    clear = {
        "expected_revision": original["revision"],
        "expected_credentials_revision": 1,
        "clear_secret": True,
    }
    result = client.put(url + "/credentials", headers=headers, json=clear).json()
    assert not result["account_key_configured"] and result["credentials_revision"] == 2


def test_metadata_fixed_origin_no_redirect_and_bounded_response(monkeypatch):
    from hub.provider_account import fetch_metadata

    targets = []
    monkeypatch.setattr(
        "hub.provider_account.pinned_url",
        lambda base, path, **kw: (
            "https://203.0.113.1/v1" + path,
            {"Host": "openrouter.ai"},
            {"sni_hostname": "openrouter.ai"},
        ),
    )
    real_client = httpx.AsyncClient
    mode = ["ok"]

    def handle(request):
        targets.append(request)
        if mode[0] == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.org/key"})
        if mode[0] == "large":
            return httpx.Response(200, content=b" " * 65537)
        return httpx.Response(200, json={"data": {"usage": 1}})

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr("hub.provider_account.httpx.AsyncClient", client)
    assert asyncio.run(fetch_metadata("SYNTHETIC", "/key")) == {"usage": 1}
    assert str(targets[0].url) == "https://203.0.113.1/api/v1/key"
    assert targets[0].headers["Host"] == "openrouter.ai"
    assert targets[0].extensions["sni_hostname"] == "openrouter.ai"
    mode[0] = "redirect"
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_metadata("SYNTHETIC", "/key"))
    assert len(targets) == 2
    mode[0] = "large"
    with pytest.raises(ValueError):
        asyncio.run(fetch_metadata("SYNTHETIC", "/key"))


def test_refresh_does_not_expose_remote_error_text(account, monkeypatch):
    app, client, headers = account
    allow_key(app, monkeypatch)

    async def fetch(key, path):
        response = httpx.Response(401, request=httpx.Request("GET", "https://openrouter.ai"))
        raise httpx.HTTPStatusError(
            "PRIVATE REMOTE LABEL SECRET", request=response.request, response=response
        )

    monkeypatch.setattr("hub.provider_account.fetch_metadata", fetch)
    result = client.post(
        "/api/providers/openrouter-default/account-status/refresh", headers=headers
    )
    assert result.json()["state"] == "error"
    assert "PRIVATE REMOTE" not in result.text
    assert "API-Schlüssels" in result.json()["error"]


def test_parallel_sqlite_credentials_cas(account, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    app, client, headers = account
    monkeypatch.setattr("hub.provider_account.encrypt", lambda *args: "ENCRYPTED")
    url = "/api/providers/openrouter-default/account-status"
    current = client.get(url).json()
    body = {
        "expected_revision": current["revision"],
        "expected_credentials_revision": 0,
        "api_key": "SYNTHETIC",
    }
    barrier = Barrier(2)

    def save():
        barrier.wait()
        return client.put(url + "/credentials", headers=headers, json=body).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: save(), range(2)))
    assert sorted(results) == [200, 409]
    assert client.get(url).json()["credentials_revision"] == 1


def test_missing_limit_metadata_is_unknown(account, monkeypatch):
    app, client, headers = account
    allow_key(app, monkeypatch)

    async def fetch(key, path):
        return {"usage": 0.3}

    monkeypatch.setattr("hub.provider_account.fetch_metadata", fetch)
    result = client.post(
        "/api/providers/openrouter-default/account-status/refresh", headers=headers
    )
    assert result.json()["state"] == "error" and result.json()["key"] is None


@pytest.mark.parametrize("failure", ["permission", "rate", "network", "invalid"])
def test_credit_error_preserves_key_usage_and_reports_cause(account, monkeypatch, failure):
    from hub.db import ProviderAccountCredential

    app, client, headers = account
    allow_key(app, monkeypatch)
    with app.state.sessions() as db:
        db.add(
            ProviderAccountCredential(
                provider_id="openrouter-default", revision=1, encrypted_secret="MANAGEMENT"
            )
        )
        db.commit()

    async def fetch(key, path):
        if path == "/key":
            return {"usage": 0.5, "limit": None, "limit_remaining": None}
        if failure in ("permission", "rate"):
            response = httpx.Response(
                403 if failure == "permission" else 429,
                request=httpx.Request("GET", "https://openrouter.ai"),
            )
            raise httpx.HTTPStatusError(
                "PRIVATE REMOTE SECRET", request=response.request, response=response
            )
        if failure == "network":
            raise httpx.ConnectError("PRIVATE REMOTE SECRET")
        return {"total_credits": "NaN", "total_usage": 0}

    monkeypatch.setattr("hub.provider_account.fetch_metadata", fetch)
    result = client.post(
        "/api/providers/openrouter-default/account-status/refresh", headers=headers
    )
    data = result.json()
    assert data["state"] == "ready" and data["key"]["usage"] == "0.5"
    assert data["account"] is None and "PRIVATE REMOTE" not in result.text
    if failure == "permission":
        assert "abgelehnt" in data["account_error"]
    elif failure == "rate":
        assert "Anfragelimit" in data["account_error"]
    else:
        assert "derzeit nicht verfügbar" in data["account_error"]


def test_downgrade_preserves_configured_management_secret(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    url = "sqlite:///" + str(tmp_path / "migration.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    migration = Config("alembic.ini")
    command.upgrade(migration, "head")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO provider_configs "
                "(id, name, kind, config, enabled, revision, is_default) "
                "VALUES ('scope', 'Synthetic', 'openrouter', '{}', 0, 1, 0)"
            )
        )
        db.execute(
            text(
                "INSERT INTO provider_account_credentials "
                "(provider_id, revision, encrypted_secret) "
                "VALUES ('scope', 1, 'synthetic-sealed-marker')"
            )
        )
    with pytest.raises(RuntimeError, match="must be preserved"):
        command.downgrade(migration, "0036")
    with engine.connect() as db:
        assert (
            db.scalar(
                text(
                    "SELECT encrypted_secret FROM provider_account_credentials "
                    "WHERE provider_id='scope'"
                )
            )
            == "synthetic-sealed-marker"
        )
