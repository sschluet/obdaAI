"""Research settings persist, freeze per run and never replace approved transport."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.config import Settings
from hub.db import Run
from hub.web_settings import WebOptions
from hub.websearch import SearchInput, search
from sqlalchemy import select

pytest_plugins = ["test_chat"]


def save(client, headers, **changes):
    current = client.get("/api/web-settings").json()
    body = {k: current[k] for k in ("revision", *WebOptions.model_fields)}
    return client.put("/api/web-settings", headers=headers, json={**body, **changes})


def test_settings_persist_cas_and_transport_is_readonly(setup):
    app, client, headers, _ = setup
    current = client.get("/api/web-settings").json()
    assert current["enabled"] and current["revision"] == 0
    assert current["endpointEditable"] is False
    assert not current["configured"]
    changed = save(client, headers, language="de", max_results=3, timeout=25)
    assert changed.status_code == 200 and changed.json()["revision"] == 1
    assert save(client, headers, revision=0).status_code == 409
    assert save(client, headers, endpoint="http://127.0.0.1/search").status_code == 422
    with TestClient(create_app(app.state.settings)) as again:
        login = again.post(
            "/api/login",
            headers={"Origin": "http://testserver"},
            json={"password": "synthetic-test-password"},
        )
        assert login.status_code == 200
        loaded = again.get("/api/web-settings").json()
        assert loaded["language"] == "de" and loaded["max_results"] == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_results", 9),
        ("max_results", 0),
        ("timeout", 31),
        ("timeout", 4),
        ("safe_search", 3),
        ("language", "fr"),
        ("enabled", "true"),
        ("max_results", True),
    ],
)
def test_validation_and_csrf(setup, field, value):
    _, client, headers, _ = setup
    assert save(client, headers, **{field: value}).status_code == 422
    assert save(client, {"Origin": "http://testserver"}).status_code == 403


def test_search_options_honor_transport_parameters_and_cap(monkeypatch):
    seen = []

    def respond(request):
        seen.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "http://invalid.example/", "title": "ignored"},
                    *[{"url": f"https://example.org/{i}", "title": str(i)} for i in range(12)],
                ]
            },
        )

    original = httpx.AsyncClient
    timeouts = []

    def client(**kwargs):
        timeouts.append(kwargs["timeout"])
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr("hub.websearch.target", lambda cfg: ("https://example.org/search", {}, {}))
    monkeypatch.setattr("hub.websearch.httpx.AsyncClient", client)
    request = SearchInput(
        request_id=str(uuid4()), query="public synthetic", public_query_approved=True
    )
    result = asyncio.run(
        search(
            Settings(),
            request,
            options=WebOptions(language="en", safe_search=2, max_results=2, timeout=20),
        )
    )
    assert len(result) == 2 and result[0]["title"] == "0"
    assert seen == [
        {"q": "public synthetic", "format": "json", "language": "en", "safesearch": "2"}
    ]
    assert timeouts == [20]
    with pytest.raises(ValueError, match="deaktiviert"):
        asyncio.run(search(Settings(), request, options=WebOptions(enabled=False)))
    assert len(seen) == 1


def test_server_disable_rejects_run_without_message_mutation(setup):
    _, client, headers, _ = setup
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    assert save(client, headers, enabled=False).status_code == 200
    result = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Synthetic research", "web_search_allowed": True},
    )
    assert result.status_code == 409 and "deaktiviert" in result.json()["detail"]
    assert client.get(f"/api/conversations/{chat}").json()["messages"] == []


def test_run_freezes_options_even_after_settings_change(setup, monkeypatch):
    app, client, headers, _ = setup

    async def noop(factory, cfg, providers, run_id):
        with factory() as db:
            row = db.get(Run, run_id)
            row.status = "succeeded"
            db.commit()

    monkeypatch.setattr("hub.api.execute_run", noop)
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    assert save(client, headers, language="de", max_results=2).status_code == 200
    result = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Synthetic research", "web_search_allowed": True},
    )
    assert result.status_code == 200
    assert save(client, headers, language="en", max_results=6).status_code == 200
    with app.state.sessions() as db:
        row = db.scalar(select(Run))
        assert row is not None
        options = json.loads(row.context_snapshot)["web_options"]
        assert options["language"] == "de" and options["max_results"] == 2
        assert options["revision"] == 1


def test_connection_test_is_synthetic_and_does_not_enable_provider(setup, monkeypatch):
    _, client, headers, _ = setup
    assert save(client, headers, enabled=False).status_code == 200
    before = client.get("/api/web-settings").json()

    async def fake(cfg, request, *, options):
        assert request.query == "SearXNG public search documentation"
        assert request.public_query_approved and options.enabled
        return [{"url": "https://example.org/"}]

    monkeypatch.setattr("hub.websearch.search", fake)
    result = client.post("/api/web-settings/test", headers=headers).json()
    assert result["success"] and result["source_count"] == 1
    assert client.get("/api/web-settings").json() == before

    async def broken(*args, **kwargs):
        raise httpx.ConnectError("PRIVATE_SECRET_ADDRESS")

    monkeypatch.setattr("hub.websearch.search", broken)
    failure = client.post("/api/web-settings/test", headers=headers)
    assert not failure.json()["success"] and "PRIVATE" not in failure.text


def test_queued_run_disable_revokes_web_at_final_boundary(setup, monkeypatch):
    app, client, headers, provider = setup
    from dataclasses import replace

    from hub.execution import execute_run
    from hub.routing import Route

    async def noop(factory, cfg, providers, run_id):
        with factory() as db:
            db.get(Run, run_id).status = "succeeded"
            db.commit()

    monkeypatch.setattr("hub.api.execute_run", noop)
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    result = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Synthetic research", "web_search_allowed": True},
    )
    assert result.status_code == 200
    with app.state.sessions() as db:
        run = db.scalar(select(Run))
        run_id = run.id
        assert json.loads(run.context_snapshot)["web_options"]["enabled"]
        run.status = "queued"
        db.commit()
    save(client, headers, enabled=False).raise_for_status()
    provider.decision = Route(capabilities=["chat", "web"], model_class="local", reason="Test")

    async def forbidden(*args, **kwargs):
        raise AssertionError("disabled queued search must never call outbound adapter")

    monkeypatch.setattr("hub.websearch.search", forbidden)
    cfg = replace(app.state.settings, search_url="https://synthetic-search.invalid/search")
    asyncio.run(execute_run(app.state.sessions, cfg, provider, run_id))
    with app.state.sessions() as db:
        run = db.get(Run, run_id)
        assert run.status == "failed"
        assert "deaktiviert" in run.error


@pytest.mark.parametrize(
    "bad",
    [
        "https://u:secret@example.org/search",
        "https://example.org/search?token=secret",
        "https://example.org:bad/search",
        "file:///search",
    ],
)
def test_invalid_endpoint_never_echoes_credentials(bad, setup):
    app, _, _, _ = setup
    from dataclasses import replace

    from hub.web_settings import view

    with app.state.sessions() as db:
        data = view(db, replace(app.state.settings, search_url=bad))
    assert data["endpoint"] == "" and not data["configured"]
    assert "secret" not in json.dumps(data)
