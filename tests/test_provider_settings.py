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
        if json.loads(request.content).get("stream"):
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"4"}}]}\n\n'
                'data: [DONE]\n\n',
            )
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


@pytest.mark.parametrize("pricing_state", ["fresh", "missing", "stale", "unavailable"])
def test_managed_cloud_route_usage_and_local_history_never_leaks(
    managed, monkeypatch, pricing_state
):
    app, _, _, cfg = managed
    cloud_cfg = replace(cfg, cloud_enabled=True)
    cloud_app = create_app(cloud_cfg)
    original = httpx.AsyncClient
    outbound = []
    catalog_requests = []

    def address(host, port, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8" if host == "openrouter.ai" else "127.0.0.1", port))]

    monkeypatch.setattr("hub.providers.socket.getaddrinfo", address)

    def handler(request):
        external = request.headers["host"] == "openrouter.ai"
        if request.method == "GET":
            catalog_requests.append(str(request.url))
            if pricing_state == "unavailable":
                return httpx.Response(503)
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
        if pricing_state in ("fresh", "stale"):
            assert (
                client.post(
                    "/api/providers/" + provider_id + "/test",
                    headers=headers,
                    json={"mode": "connection"},
                ).status_code
                == 200
            )
        if pricing_state == "stale":
            with app.state.sessions() as db:
                row = db.get(ProviderConfig, provider_id)
                data = json.loads(row.config)
                data["pricing"]["verified_at"] = 0
                row.config = json.dumps(data)
                db.commit()
        chat = client.post(
            "/api/conversations", headers=headers, json={"cloud_allowed": True}
        ).json()["id"]
        client.post(
            "/api/conversations/" + chat + "/messages",
            headers=headers,
            json={"content": "complex synthetic question"},
        )
        detail = client.get("/api/conversations/" + chat).json()
        if pricing_state == "unavailable":
            assert detail["runs"][-1]["status"] == "failed" and not outbound
        else:
            assert detail["runs"][-1]["status"] == "succeeded"
            assert detail["runs"][-1]["provider"] == "openrouter"
            assert detail["runs"][-1]["cost"] == 0.0002
            assert detail["runs"][-1]["cost_estimate"] > 0
            assert len(outbound) == 1
        assert len(catalog_requests) == (2 if pricing_state == "stale" else 1)
        prior_outbound = len(outbound)
        prior_catalog = len(catalog_requests)
        # Expired metadata must never trigger even a public external request
        # while processing a LOCAL_ONLY question.
        with app.state.sessions() as db:
            row = db.get(ProviderConfig, provider_id)
            data = json.loads(row.config)
            if data.get("pricing"):
                data["pricing"]["verified_at"] = 0
                row.config = json.dumps(data)
                db.commit()
        private = client.post("/api/conversations", headers=headers, json={}).json()["id"]
        client.post(
            "/api/conversations/" + private + "/messages",
            headers=headers,
            json={"content": "PRIVATE_SYNTHETIC_FIXTURE"},
        )
        assert len(outbound) == prior_outbound and len(catalog_requests) == prior_catalog
        assert "PRIVATE_SYNTHETIC_FIXTURE" not in json.dumps(outbound)
        assert client.get("/api/conversations/" + private).json()["runs"][-1]["provider"] == "local"
        with app.state.sessions() as db:
            reservation = db.get(BudgetReservation, detail["runs"][-1]["id"])
            if pricing_state == "unavailable":
                assert reservation is None
            else:
                assert reservation.measured == 0.0002


@pytest.mark.parametrize(
    "kind,url,model",
    [
        ("openai", "https://api.openai.com/v1", "gpt-4.1-mini"),
        ("anthropic", "https://api.anthropic.com/v1", "claude-haiku-4-5-20251001"),
    ],
)
def test_prepare_native_encrypted_connection_without_server_egress(managed, kind, url, model):
    app, client, headers, cfg = managed
    response = client.post(
        "/api/providers",
        headers=headers,
        json={
            **payload("openrouter"),
            "kind": kind,
            "base_url": url,
            "model": model,
            "api_key": "SYNTHETIC_NATIVE_PROVIDER_KEY",
            "is_default": True,
        },
    )
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["secret_ref"] == "encrypted" and "SYNTHETIC_NATIVE_PROVIDER_KEY" not in response.text
    assert (
        client.post(
            "/api/providers/" + row["id"] + "/test", headers=headers, json={"mode": "connection"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/conversations",
            headers=headers,
            json={"cloud_allowed": True, "cloud_provider": kind},
        ).status_code
        == 409
    )
    private = client.post("/api/conversations", headers=headers, json={"cloud_provider": kind})
    assert private.status_code == 200 and private.json()["cloud_provider"] == kind
    assert (
        client.patch(
            "/api/conversations/" + private.json()["id"],
            headers=headers,
            json={"cloud_provider": "openrouter"},
        ).status_code
        == 422
    )
    with app.state.sessions() as db:
        stored = db.get(ProviderConfig, row["id"])
        assert decrypt(cfg, row["id"], stored.encrypted_secret) == "SYNTHETIC_NATIVE_PROVIDER_KEY"
    assert kind not in client.get("/api/providers").json()["external_provider_kinds"]


def test_native_consent_reservation_stream_and_cost_basis_end_to_end(managed, monkeypatch):
    from hub.native_providers import REVIEWED_AT
    from hub.providers import Providers
    from hub.routing import Route

    _, _, _, cfg = managed
    cfg = replace(cfg, cloud_enabled=True, external_provider_kinds=("openrouter", "openai"))
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        events = [
            {"type": "response.output_text.delta", "delta": "Blue"},
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                },
            },
        ]
        return httpx.Response(
            200, content="".join("data: " + json.dumps(e) + "\n\n" for e in events)
        )

    monkeypatch.setattr(
        "hub.providers.socket.getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("1.1.1.1", 443))],
    )
    monkeypatch.setattr(
        "hub.native_providers.httpx.AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)),
    )
    monkeypatch.setattr("hub.native_providers.REVIEWED_AT", int(time.time()))

    async def route(self, parts, roles):
        if any(p.label == Privacy.LOCAL_ONLY for p in parts):
            return Route(
                capabilities=["chat"], model_class="local", reason="private", answer="Local"
            )
        return Route(
            capabilities=["chat"], model_class="cloud", reason="synthetic native route", answer=None
        )

    async def title(self, parts, roles):
        return "Synthetic native conversation"

    monkeypatch.setattr(Providers, "route", route)
    monkeypatch.setattr(Providers, "title", title)
    app = create_app(cfg)
    with TestClient(app) as client:
        login = client.post(
            "/api/login",
            headers={"Origin": cfg.origin},
            json={"password": "synthetic-test-password"},
        )
        h = {"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]}
        body = {
            **payload("openrouter"),
            "kind": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
            "api_key": "SYNTHETIC_NATIVE_PROVIDER_KEY",
            "is_default": True,
            "monthly_budget": 0.02,
            "max_run_cost": 0.01,
            "output_tokens": 128,
        }
        result = client.post("/api/providers", headers=h, json=body)
        assert result.status_code == 200, result.text
        private = client.post(
            "/api/conversations", headers=h, json={"cloud_provider": "openai"}
        ).json()
        private_reply = client.post(
            "/api/conversations/" + private["id"] + "/messages",
            headers=h,
            json={"content": "Private synthetic blue", "request_id": str(uuid.uuid4())},
        )
        assert private_reply.status_code == 200 and requests == []
        assert (
            client.get("/api/conversations/" + private["id"]).json()["runs"][-1]["provider"]
            == "local"
        )
        # Selecting a provider alone grants no transfer. A private route stays local.
        public = client.post(
            "/api/conversations",
            headers=h,
            json={"cloud_provider": "openai", "cloud_allowed": True},
        ).json()
        response = client.post(
            "/api/conversations/" + public["id"] + "/messages",
            headers=h,
            json={"content": "Synthetic blue", "request_id": str(uuid.uuid4())},
        )
        assert response.status_code == 200, response.text
        chat = client.get("/api/conversations/" + public["id"]).json()
        run = chat["runs"][-1]
        assert run["status"] == "succeeded" and run["provider"] == "openai", run
        assert run["cost_basis"] == "usage_estimate" and run["cost"] == pytest.approx(0.000072)
        assert run["cost_estimate"] >= run["cost"]
        assert len(requests) == 1 and json.loads(requests[0].content)["store"] is False
        with app.state.sessions() as db:
            reservation = db.get(BudgetReservation, run["id"])
            assert (
                reservation.provider_id == result.json()["id"]
                and reservation.measured == run["cost"]
            )
        assert (
            client.patch(
                "/api/conversations/" + public["id"],
                headers=h,
                json={"cloud_provider": "anthropic"},
            ).status_code
            == 422
        )
        assert client.get("/api/conversations/" + private["id"]).json()["cloud_allowed"] is False
    assert REVIEWED_AT > 0
