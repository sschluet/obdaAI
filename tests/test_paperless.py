"""Real Paperless protocol, bounded private reads and revocation boundaries."""

import base64
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hub.auth import require_session
from hub.config import Settings
from hub.db import Base, session_factory
from hub.integrations import Integration
from hub.paperless_api import install_paperless_api, perform
from hub.paperless_client import document, download, list_documents
from hub.provider_settings import encrypt


@pytest.fixture
def target(monkeypatch):
    monkeypatch.setattr(
        "hub.integration_transport.socket.getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("192.168.8.20", 443))],
    )
    return Settings(integration_targets_enabled=True)


def payload(identifier=7):
    return {
        "id": identifier,
        "title": "Synthetic invoice",
        "content": "Private OCR",
        "tags": [1],
        "correspondent": None,
        "document_type": None,
    }


def test_search_pins_target_token_and_never_follows_next(target):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"count": 100, "next": "https://evil.test/?token=stolen", "results": [payload()]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = list_documents(
            client,
            target,
            "https://paperless.example.test/",
            "synthetic-token",
            query="invoice",
            page_size=1,
        )
    assert result["has_next"] and len(requests) == 1
    assert requests[0].url.host == "192.168.8.20"
    assert requests[0].headers["host"] == "paperless.example.test"
    assert requests[0].headers["authorization"] == "Token synthetic-token"
    assert requests[0].extensions["sni_hostname"] == "paperless.example.test"
    assert requests[0].url.params["query"] == "invoice"
    assert "content" not in result["results"][0]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://evil.test"}),
        httpx.Response(401),
        httpx.Response(200, text="login"),
        httpx.Response(200, json={"id": 9}),
    ],
)
def test_document_invalid_response_fails(target, response):
    with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(ValueError):
            document(client, target, "https://paperless.example.test/api/", "token", 7)


def test_original_uses_fixed_path_and_original_parameter(target):
    def handler(request):
        assert request.url.path == "/api/documents/7/download/"
        assert request.url.params["original"] == "true"
        return httpx.Response(
            200, content=b"%PDF-synthetic", headers={"content-type": "application/pdf"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        data, mime = download(client, target, "https://paperless.example.test", "token", 7)
    assert data == b"%PDF-synthetic" and mime == "application/pdf"


def test_json_and_original_response_limits(target, monkeypatch):
    monkeypatch.setattr("hub.paperless_client.MAX_JSON_BYTES", 16)
    monkeypatch.setattr("hub.paperless_client.MAX_DOWNLOAD_BYTES", 16)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=b"x" * 17, headers={"content-type": "application/json"}
            )
        )
    ) as client:
        with pytest.raises(ValueError, match="limit"):
            document(client, target, "https://paperless.example.test", "token", 7)
        with pytest.raises(ValueError, match="limit"):
            download(client, target, "https://paperless.example.test", "token", 7)


@pytest.fixture
def api(tmp_path, target):
    key = tmp_path / "key"
    key.write_text(base64.b64encode(b"p" * 32).decode())
    key.chmod(0o600)
    cfg = Settings(
        database_url="sqlite:///" + str(tmp_path / "paperless.sqlite"),
        secrets_key_file=str(key),
        integration_targets_enabled=True,
    )
    factory = session_factory(cfg.database_url)
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as db:
        row = Integration(
            name="Synthetic",
            kind="paperless",
            enabled=True,
            config=json.dumps({"url": "https://paperless.example.test", "auth": "api_key"}),
        )
        db.add(row)
        db.flush()
        row.encrypted_secret = encrypt(cfg, "integration:" + row.id, "synthetic-token")
        identifier = row.id
        db.commit()
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    install_paperless_api(app, cfg, factory)
    with TestClient(app) as client:
        yield client, factory, cfg, identifier


def test_api_uses_profile_secret_rejects_stale_and_disabled(api, monkeypatch):
    client, factory, _, identifier = api

    def operation(http, cfg, url, token, **kwargs):
        assert token == "synthetic-token"
        return {"label": "LOCAL_ONLY", "count": 0, "results": []}

    monkeypatch.setattr("hub.paperless_api.list_documents", operation)
    path = f"/api/integrations/{identifier}/paperless/documents"
    response = client.get(path, params={"expected_revision": 1})
    assert response.status_code == 200 and "synthetic-token" not in response.text
    assert client.get(path, params={"expected_revision": 2}).status_code == 409
    with factory() as db:
        row = db.get(Integration, identifier)
        row.enabled = False
        db.commit()
    assert client.get(path, params={"expected_revision": 1}).status_code == 409


def test_midflight_disable_discards_result(api):
    _, factory, cfg, identifier = api

    def operation(*args):
        with factory() as db:
            row = db.get(Integration, identifier)
            row.enabled = False
            db.commit()
        return {"content": "must not escape"}

    with factory() as db:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as failure:
            perform(db, cfg, identifier, 1, operation)
    assert failure.value.status_code == 409


def test_selected_context_private_and_revocation(api, monkeypatch):
    import asyncio

    from hub.paperless_api import collect_context, validate_selection
    from hub.policy import Privacy, check_egress

    _, factory, cfg, identifier = api
    selection = {"bindings": [{"id": identifier, "revision": 1, "kind": "paperless"}]}
    monkeypatch.setattr(
        "hub.paperless_api.list_documents", lambda *a, **kw: {"results": [payload()]}
    )
    monkeypatch.setattr("hub.paperless_api.document", lambda *a, **kw: payload())
    parts = asyncio.run(collect_context(factory, cfg, selection, "Finde meine Rechnung"))
    assert len(parts) == 1 and parts[0].label == Privacy.LOCAL_ONLY
    assert "Private OCR" in parts[0].content
    assert parts[0].source_id == "paperless:" + identifier + ":7"
    with pytest.raises(PermissionError):
        check_egress(parts, external=True, provider_id="openrouter", grants=[])
    with factory() as db:
        row = db.get(Integration, identifier)
        row.revision += 1
        db.commit()
    with factory() as db:
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            validate_selection(db, selection)


def test_query_only_bounded_literal_terms():
    from hub.paperless_api import search_query

    result = search_query('Bitte suche meine Dokumente Rechnung "secret:*" AND 2025')
    assert "*" not in result and len(result) <= 500
    assert '"rechnung"' in result


def test_exact_document_context_bypasses_imprecise_search(api, monkeypatch):
    import asyncio

    from hub.paperless_api import collect_context

    _, factory, cfg, identifier = api
    monkeypatch.setattr(
        "hub.paperless_api.list_documents",
        lambda *a, **kw: pytest.fail("No archive search for exact ID"),
    )
    monkeypatch.setattr("hub.paperless_api.document", lambda *a, **kw: payload(a[-1]))
    parts = asyncio.run(
        collect_context(
            factory,
            cfg,
            {"bindings": [{"id": identifier, "revision": 1, "kind": "paperless"}]},
            "Fasse Paperless #7 zusammen",
        )
    )
    assert parts[0].source_id.endswith(":7")


def test_unselected_profiles_never_add_paperless_context(api):
    import asyncio

    from hub.paperless_api import collect_context

    _, factory, cfg, identifier = api
    assert (
        asyncio.run(
            collect_context(
                factory,
                cfg,
                {"bindings": [{"id": identifier, "revision": 1, "kind": "mcp"}]},
                "Hello",
            )
        )
        == []
    )
