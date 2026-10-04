import base64
import json
import os
import time
import uuid
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.budgets import reserve, settle
from hub.db import BudgetReservation, ProviderConfig, ProviderRevision
from hub.policy import ContextPart, Privacy
from hub.provider_settings import decrypt, seed
from sqlalchemy import select

pytest_plugins = ["test_chat"]


@pytest.fixture
def managed(setup, tmp_path):
    app, _, _, _ = setup
    key = tmp_path / "encryption.key"
    key.write_text(base64.b64encode(os.urandom(32)).decode())
    key.chmod(0o600)
    cfg = replace(
        app.state.settings,
        secrets_key_file=str(key),
        local_base_url="http://127.0.0.1:11444/v1",
        local_allowed_ip="127.0.0.1",
        local_model="local-fixture",
        cloud_enabled=False,
    )
    managed_app = create_app(cfg)
    with TestClient(managed_app) as client:
        login = client.post(
            "/api/login",
            headers={"Origin": cfg.origin},
            json={"password": "synthetic-test-password"},
        )
        headers = {"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]}
        client.get("/api/providers").raise_for_status()
        yield managed_app, client, headers, cfg


def payload(kind="local"):
    return {
        "name": "Synthetic provider",
        "kind": kind,
        "base_url": "http://127.0.0.1:11444/v1" if kind == "local" else "https://openrouter.ai/v1",
        "model": "local-fixture" if kind == "local" else "cloud-fixture",
        "capabilities": ["text", "structured"] if kind == "local" else ["text"],
        "allowed_labels": ["LOCAL_ONLY"] if kind == "local" else ["CLOUD_ALLOWED"],
    }


def test_encrypted_secret_revisions_and_no_validation_echo(managed):
    app, client, headers, cfg = managed
    body = dict(payload(), api_key="SYNTHETIC_PRIVATE_KEY")
    response = client.post("/api/providers", headers=headers, json=body)
    assert response.status_code == 200
    result = response.json()
    provider_id = result["id"]
    assert result["secret_ref"] == "encrypted"
    assert "SYNTHETIC_PRIVATE_KEY" not in response.text
    with app.state.sessions() as db:
        row = db.get(ProviderConfig, provider_id)
        assert "SYNTHETIC_PRIVATE_KEY" not in row.encrypted_secret
        assert decrypt(cfg, provider_id, row.encrypted_secret) == "SYNTHETIC_PRIVATE_KEY"
        for revision in db.scalars(select(ProviderRevision)):
            assert "SYNTHETIC_PRIVATE_KEY" not in revision.config
    body["revision"] = result["revision"]
    body["name"] = "Changed provider"
    assert (
        client.put("/api/providers/" + provider_id, headers=headers, json=body).status_code == 200
    )
    assert (
        client.put("/api/providers/" + provider_id, headers=headers, json=body).status_code == 409
    )
    bad = dict(body, kind="openrouter")
    r = client.post("/api/providers", headers=headers, json=bad)
    assert r.status_code == 422 and "SYNTHETIC_PRIVATE_KEY" not in r.text
    assert client.get("/api/providers/" + provider_id + "/revisions").status_code == 200
    assert client.post("/api/providers", json=payload()).status_code == 403


@pytest.mark.parametrize(
    "base",
    [
        "http://127.0.0.1:8006/v1",
        "http://169.254.169.254/v1",
        "https://example.com/v1",
        "http://127.0.0.1:11444/v1?key=x",
    ],
)
def test_local_network_scope_is_server_owned(managed, base):
    _, client, headers, _ = managed
    assert (
        client.post(
            "/api/providers", headers=headers, json=dict(payload(), base_url=base)
        ).status_code
        == 422
    )


def test_cloud_server_gate_blocks_both_test_types(managed):
    _, client, headers, _ = managed
    row = client.post(
        "/api/providers", headers=headers, json=dict(payload("openrouter"), api_key="synthetic")
    ).json()
    for mode in ("model", "connection"):
        assert (
            client.post(
                "/api/providers/" + row["id"] + "/test",
                headers=headers,
                json={"mode": mode, "request_id": str(uuid.uuid4())},
            ).status_code
            == 409
        )


def test_budget_reserves_unknown_cost_and_blocks_stale_pricing(managed):
    app, _, _, cfg = managed
    part = ContextPart(
        content="synthetic", source_id="budget", revision=1, label=Privacy.CLOUD_ALLOWED
    )
    with app.state.sessions() as db:
        seed(db, cfg)
        row = db.get(ProviderConfig, "openrouter-default")
        data = json.loads(row.config)
        data.update(
            monthly_budget=0.01,
            max_run_cost=0.009,
            output_tokens=128,
            pricing={"input": "0.00001", "output": "0.00001", "verified_at": time.time()},
        )
        row.config = json.dumps(data)
        db.commit()
        amount = reserve(db, row, "reservation-one", [part])
        db.commit()
        assert amount > 0
        settle(db, "reservation-one", None)
        db.commit()
        assert db.get(BudgetReservation, "reservation-one").measured is None
        assert reserve(db, row, "reservation-one", [part]) == amount
        reserve(db, row, "reservation-two", [part])
        db.commit()
        with pytest.raises(PermissionError):
            reserve(db, row, "reservation-three", [part])
        db.rollback()
        settle(db, "reservation-one", 0.0)
        db.commit()
        reserve(db, row, "reservation-three", [part])
        db.commit()
        data["pricing"]["verified_at"] = 0
        row.config = json.dumps(data)
        db.commit()
        with pytest.raises(ValueError):
            reserve(db, row, "reservation-four", [part])


def test_connection_and_queued_local_model_test(managed, monkeypatch):
    _, client, headers, _ = managed
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "local-fixture"}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "capabilities": ["chat"],
                                    "model_class": "local",
                                    "reason": "fixture",
                                    "answer": "4",
                                }
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    result = client.post(
        "/api/providers/local-default/test", headers=headers, json={"mode": "connection"}
    )
    assert result.status_code == 200 and result.json()["models"] == ["local-fixture"]
    request = {"mode": "model", "request_id": str(uuid.uuid4())}
    r = client.post("/api/providers/local-default/test", headers=headers, json=request)
    assert r.status_code == 200
    test_id = r.json()["id"]
    for _ in range(100):
        probe = client.get("/api/provider-tests/" + test_id).json()
        if probe["status"] not in ("queued", "running"):
            break
        time.sleep(0.01)
    assert probe["status"] == "succeeded"
    count = len(calls)
    client.post("/api/providers/local-default/test", headers=headers, json=request)
    assert len(calls) == count


def test_managed_cloud_route_usage_and_local_history_never_leaks(managed, monkeypatch):
    app, _, _, cfg = managed
    cloud_cfg = replace(cfg, cloud_enabled=True)
    cloud_app = create_app(cloud_cfg)
    original = httpx.AsyncClient
    outbound = []

    def address(host, port, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8" if host == "openrouter.ai" else "127.0.0.1", port))]

    monkeypatch.setattr("hub.providers.socket.getaddrinfo", address)

    def handler(request):
        external = request.headers["host"] == "openrouter.ai"
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "cloud-fixture",
                            "context_length": 32768,
                            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                        }
                    ]
                },
            )
        body = json.loads(request.content)
        if external:
            outbound.append(body)
        if not body.get("stream"):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "capabilities": ["chat"],
                                        "model_class": "cloud",
                                        "reason": "complex fixture",
                                        "answer": None,
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            text="data: "
            + json.dumps({"choices": [{"delta": {"content": "4"}}]})
            + "\n\ndata: "
            + json.dumps({"choices": [], "usage": {"cost": 0.0002}})
            + "\n\ndata: [DONE]\n\n",
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    with TestClient(cloud_app) as client:
        login = client.post(
            "/api/login",
            headers={"Origin": cfg.origin},
            json={"password": "synthetic-test-password"},
        )
        headers = {"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]}
        body = dict(
            payload("openrouter"),
            api_key="synthetic",
            is_default=True,
            monthly_budget=0.1,
            max_run_cost=0.01,
        )
        result = client.post("/api/providers", headers=headers, json=body)
        assert result.status_code == 200
        provider_id = result.json()["id"]
        assert (
            client.post(
                "/api/providers/" + provider_id + "/test",
                headers=headers,
                json={"mode": "connection"},
            ).status_code
            == 200
        )
        chat = client.post(
            "/api/conversations", headers=headers, json={"cloud_allowed": True}
        ).json()["id"]
        client.post(
            "/api/conversations/" + chat + "/messages",
            headers=headers,
            json={"content": "complex synthetic question"},
        )
        detail = client.get("/api/conversations/" + chat).json()
        assert (
            detail["runs"][-1]["status"] == "succeeded"
            and detail["runs"][-1]["provider"] == "openrouter"
        )
        assert detail["runs"][-1]["cost"] == 0.0002
        assert detail["runs"][-1]["cost_estimate"] > 0
        assert len(outbound) == 1
        private = client.post("/api/conversations", headers=headers, json={}).json()["id"]
        client.post(
            "/api/conversations/" + private + "/messages",
            headers=headers,
            json={"content": "PRIVATE_SYNTHETIC_FIXTURE"},
        )
        assert len(outbound) == 1
        assert "PRIVATE_SYNTHETIC_FIXTURE" not in json.dumps(outbound)
        assert client.get("/api/conversations/" + private).json()["runs"][-1]["provider"] == "local"
        with app.state.sessions() as db:
            assert db.get(BudgetReservation, detail["runs"][-1]["id"]).measured == 0.0002
