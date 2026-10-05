import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import Message, Run
from hub.policy import CloudGrant, ContextPart, check_egress
from hub.providers import Providers, pinned_url
from hub.routing import Route


class FakeProviders:
    def __init__(self, route: Route | None = None, fail: bool = False) -> None:
        self.calls = 0
        self.stream_calls: list[bool] = []
        self.fail = fail
        self.decision = route or Route(
            capabilities=["chat"],
            model_class="local",
            reason="simple fixture",
            answer="SYNTHETIC_ANSWER",
        )

    async def title(self, parts: list[ContextPart], roles: list[str]) -> str:
        return "Synthetic conversation"

    async def route(self, parts: list[ContextPart], roles: list[str]) -> Route:
        self.calls += 1
        if self.fail:
            raise httpx.ConnectError("SENSITIVE_INTERNAL_ERROR")
        return self.decision

    async def stream(
        self,
        parts: list[ContextPart],
        roles: list[str],
        *,
        external: bool,
        grants: list[CloudGrant],
    ) -> AsyncIterator[str]:
        check_egress(
            parts,
            external=external,
            provider_id="openrouter" if external else "local",
            grants=grants,
        )
        self.stream_calls.append(external)
        yield "SYNTHETIC_"
        yield "STREAM"


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = "sqlite:///" + str(tmp_path / "test.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    settings = Settings(
        database_url=url,
        origin="http://testserver",
        secure_cookie=False,
        password_hash=password_hash("synthetic-test-password"),
        cloud_enabled=True,
    )
    application = create_app(settings)
    provider = FakeProviders()
    application.state.providers = provider
    with TestClient(application) as client:
        result = client.post(
            "/api/login",
            json={"password": "synthetic-test-password"},
            headers={"Origin": "http://testserver"},
        )
        assert result.status_code == 200
        headers = {"Origin": "http://testserver", "X-CSRF-Token": result.json()["csrf"]}
        yield application, client, headers, provider


def new_chat(client: TestClient, headers: dict[str, str], cloud: bool = False) -> str:
    r = client.post("/api/conversations", json={"cloud_allowed": cloud}, headers=headers)
    assert r.status_code == 200
    return r.json()["id"]


def test_simple_local_one_call_persisted(setup):
    app, client, headers, provider = setup
    chat_id = new_chat(client, headers)
    result = client.post(
        f"/api/conversations/{chat_id}/messages",
        json={"content": "synthetic question"},
        headers=headers,
    )
    assert result.status_code == 200
    assert "SYNTHETIC_ANSWER" in result.text and "succeeded" in result.text
    assert provider.calls == 1 and provider.stream_calls == []
    detail = client.get("/api/conversations/" + chat_id).json()
    assert len(detail["messages"]) == 2
    assert all(m["label"] == "LOCAL_ONLY" for m in detail["messages"])
    assert detail["runs"][0]["router_seconds"] >= 0
    assert detail["runs"][0]["cost"] is None


def test_cloud_requires_explicit_conversation_and_history_permission(setup):
    app, client, headers, provider = setup
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="complex fixture")
    local_id = new_chat(client, headers)
    client.post(
        f"/api/conversations/{local_id}/messages", json={"content": "local"}, headers=headers
    )
    cloud_id = new_chat(client, headers, True)
    result = client.post(
        f"/api/conversations/{cloud_id}/messages", json={"content": "allowed"}, headers=headers
    )
    assert "openrouter" in result.text
    assert provider.stream_calls == [False, True]
    with app.state.sessions() as db:
        db.add(
            Message(
                conversation_id=cloud_id,
                role="user",
                content="protected fixture",
                label="LOCAL_ONLY",
            )
        )
        db.commit()
    client.post(
        f"/api/conversations/{cloud_id}/messages", json={"content": "follow up"}, headers=headers
    )
    assert provider.stream_calls[-1] is False


def test_router_outage_does_not_fallback_or_leak_error(setup):
    app, client, headers, provider = setup
    provider.fail = True
    chat_id = new_chat(client, headers, True)
    result = client.post(
        f"/api/conversations/{chat_id}/messages", json={"content": "fixture"}, headers=headers
    )
    assert "failed" in result.text and "SENSITIVE_INTERNAL_ERROR" not in result.text
    assert provider.stream_calls == []
    assert client.get("/api/conversations/" + chat_id).json()["runs"][0]["status"] == "failed"


def test_tools_never_faked(setup):
    app, client, headers, provider = setup
    provider.decision = Route(
        capabilities=["web", "artifact"], model_class="local", reason="fixture"
    )
    chat_id = new_chat(client, headers)
    result = client.post(
        f"/api/conversations/{chat_id}/messages", json={"content": "fixture"}, headers=headers
    )
    assert "kein Werkzeug" in result.text
    assert provider.stream_calls == []
    assert len(client.get("/api/conversations/" + chat_id).json()["messages"]) == 1


def test_auth_csrf_and_origin(setup):
    app, client, headers, provider = setup
    assert (
        client.post(
            "/api/conversations", json={}, headers={"Origin": "http://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/conversations", json={}, headers={"Origin": "http://testserver"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/api/conversations/missing", json={"cloud_allowed": True}, headers=headers
        ).status_code
        == 422
    )
    assert client.get("/api/settings").json()["autonomous_changes"] == "paused"
    client.post("/api/logout", headers=headers)
    assert client.get("/api/conversations").status_code == 401


def test_rename_archive_delete_and_session_survives_restart(setup):
    app, client, headers, provider = setup
    chat_id = new_chat(client, headers)
    assert (
        client.patch(
            "/api/conversations/" + chat_id, json={"title": "Fixture title"}, headers=headers
        ).status_code
        == 200
    )
    assert client.get("/api/conversations?q=Fixture").json()[0]["title"] == "Fixture title"
    with TestClient(create_app(app.state.settings)) as restarted:
        restarted.cookies.update(client.cookies)
        assert restarted.get("/api/me").status_code == 200
        assert restarted.get("/api/conversations/" + chat_id).json()["title"] == "Fixture title"
    assert (
        client.patch(
            "/api/conversations/" + chat_id, json={"archived": True}, headers=headers
        ).status_code
        == 200
    )
    assert client.get("/api/conversations").json() == []
    assert len(client.get("/api/conversations?archived=true").json()) == 1
    assert client.delete("/api/conversations/" + chat_id, headers=headers).status_code == 200
    assert client.get("/api/conversations/" + chat_id).status_code == 404


def test_restart_records_interrupted_run(setup):
    app, client, headers, provider = setup
    chat_id = new_chat(client, headers)
    with app.state.sessions() as db:
        db.add(Run(conversation_id=chat_id, status="streaming"))
        db.commit()
    with TestClient(create_app(app.state.settings)) as restarted:
        restarted.cookies.update(client.cookies)
        assert (
            restarted.get("/api/conversations/" + chat_id).json()["runs"][0]["status"]
            == "interrupted"
        )


def test_final_boundary_blocks_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = Providers(Settings(cloud_enabled=True))
    monkeypatch.setattr(
        provider, "_target", lambda external: pytest.fail("Network boundary reached")
    )

    async def run() -> None:
        with pytest.raises(PermissionError):
            async for _ in provider.stream(
                [ContextPart(content="fixture", source_id="x", revision=1)],
                ["user"],
                external=True,
                grants=[],
            ):
                pass

    asyncio.run(run())


def test_pinned_dns_redirect_and_metadata_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(host, port, **kwargs):
        return [(2, 1, 6, "", ("169.254.169.254", port))]

    monkeypatch.setattr("socket.getaddrinfo", resolve)
    with pytest.raises(ValueError):
        pinned_url(
            "http://local.example/v1",
            "/chat/completions",
            external=False,
            allowed_ip="169.254.169.254",
        )
    with pytest.raises(ValueError):
        pinned_url("https://evil.example/v1", "/chat/completions", external=True)
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 11435))]
    )
    target, headers, ext = pinned_url(
        "http://local.example:11435/v1", "/chat/completions", external=False, allowed_ip="127.0.0.1"
    )
    assert target == "http://127.0.0.1:11435/v1/chat/completions"
    assert headers["Host"] == "local.example:11435"
    assert ext["sni_hostname"] == "local.example"


def test_public_endpoint_cannot_be_mislabelled_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))])
    with pytest.raises(ValueError, match="public Internet"):
        pinned_url(
            "https://example.com/v1", "/chat/completions", external=False, allowed_ip="8.8.8.8"
        )


def test_local_mode_binds_request_and_disables_web_and_cloud(setup):
    from uuid import uuid4

    from sqlalchemy import select

    app, client, headers, provider = setup
    chat_id = new_chat(client, headers, cloud=True)
    request_id = str(uuid4())
    body = {"content": "Synthetic local mode", "local_only": True, "request_id": request_id}
    assert (
        client.post(
            f"/api/conversations/{chat_id}/messages", json=body, headers=headers
        ).status_code
        == 200
    )
    with app.state.sessions() as db:
        msg = db.scalar(select(Message).where(Message.role == "user"))
        run = db.scalar(select(Run).where(Run.conversation_id == chat_id))
        assert msg.label == "LOCAL_ONLY"
        import json

        assert all(p["label"] == "LOCAL_ONLY" for p in json.loads(run.context_snapshot)["parts"])
    assert (
        client.post(
            f"/api/conversations/{chat_id}/messages",
            json={**body, "local_only": False},
            headers=headers,
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/conversations/{chat_id}/messages",
            json={"content": "Synthetic", "local_only": True, "web_search_allowed": True},
            headers=headers,
        ).status_code
        == 422
    )
    assert not any(provider.stream_calls)


def test_local_retry_keeps_original_cloud_label_but_uses_local_snapshot(setup):
    import json
    from uuid import uuid4

    from sqlalchemy import select

    app, client, headers, _ = setup
    chat_id = new_chat(client, headers, cloud=True)
    client.post(
        f"/api/conversations/{chat_id}/messages",
        json={"content": "Synthetic public text"},
        headers=headers,
    )
    result = client.post(
        f"/api/conversations/{chat_id}/retry",
        json={"request_id": str(uuid4()), "local_only": True},
        headers=headers,
    )
    assert result.status_code == 200
    with app.state.sessions() as db:
        original = db.scalar(select(Message).where(Message.role == "user"))
        run = db.scalar(select(Run).order_by(Run.started.desc()))
        assert original.label == "CLOUD_ALLOWED"
        assert all(p["label"] == "LOCAL_ONLY" for p in json.loads(run.context_snapshot)["parts"])


def test_existing_openrouter_consent_remains_bound_and_cannot_switch(setup):
    _, client, headers, _ = setup
    chat_id = new_chat(client, headers, cloud=True)
    chat = client.get("/api/conversations/" + chat_id).json()
    assert chat["cloud_provider"] == "openrouter"
    assert (
        client.patch(
            "/api/conversations/" + chat_id, headers=headers, json={"cloud_provider": "openai"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/conversations",
            headers=headers,
            json={"cloud_allowed": True, "cloud_provider": "openai"},
        ).status_code
        == 409
    )
