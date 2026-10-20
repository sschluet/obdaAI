"""Synthetic native archive transport and evidence, distinct from real VM acceptance."""

import copy
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from hub import agent_paperless as archive
from hub import agent_tools as tools
from hub.agent_schema import validate
from hub.config import Settings
from hub.paperless_client import metadata
from pydantic import ValidationError

CONFIG = {"kind": "paperless", "url": "https://archive.example.test/api"}


def row(identifier=7, **extra):
    return {"id": identifier, "title": "Synthetic invoice", "tags": [], **extra}


@pytest.fixture
def transport(monkeypatch):
    calls, boundaries = [], []
    response = {"status": 200, "body": {"count": 1, "results": [row()]}}
    original = httpx.Client

    def reply(request):
        assert boundaries[-1] == "dispatch"
        assert request.headers["Authorization"] == "Token synthetic-token"
        assert str(request.url).startswith("https://192.168.50.20/api/")
        calls.append(request)
        return httpx.Response(response["status"], json=response["body"])

    def pin(*args):
        boundaries.append("dns")
        return "https://192.168.50.20", {"Host": "archive.example.test"}, {}

    monkeypatch.setattr(tools, "pinned_target", pin)
    monkeypatch.setattr(
        tools.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(reply), **kw),
    )

    def read(arguments, rules=None):
        return tools.invoke(
            Settings(),
            CONFIG,
            "synthetic-token",
            "paperless.read",
            arguments,
            rules or tools.Rules(enabled=True, http_prefixes=["/api/"]),
            lambda: boundaries.append("dispatch"),
        )

    return read, response, calls, boundaries


def test_search_real_transport_canonical_path_and_pinned_final_gate(transport):
    read, _, calls, boundaries = transport
    result = read({"operation": "search", "query": "Synthetic invoice", "limit": 3, "page": 2})
    assert boundaries == ["dns", "dispatch"]
    assert len(calls) == 1
    assert calls[0].url.path == "/api/documents/"
    assert dict(calls[0].url.params) == {
        "page": "2",
        "page_size": "3",
        "ordering": "-created",
        "fields": (
            "id,title,created,added,modified,correspondent,document_type,tags,original_file_name"
        ),
        "query": "Synthetic invoice",
    }
    assert result["label"] == "LOCAL_ONLY"
    assert result["data"]["results"][0]["id"] == 7
    assert result["data"]["page"] == 2
    assert not result["data"]["has_next"]


def test_document_uses_observed_id_and_validated_bounded_ocr(transport):
    read, response, calls, _ = transport
    response["body"] = row(content="synthetic OCR " * 10000)
    result = read({"operation": "document", "document_id": 7})
    assert calls[0].url.path == "/api/documents/7/"
    assert not calls[0].url.query
    assert result["data"]["content_truncated"]
    assert len(result["data"]["content"]) == 100000
    response["body"] = row(8)
    with pytest.raises(ValueError, match="mismatch"):
        read({"operation": "document", "document_id": 7})


@pytest.mark.parametrize("status", [301, 401, 403, 404, 500])
def test_typed_archive_read_rejects_non200_without_replaying_or_private_error(transport, status):
    read, response, calls, _ = transport
    response.update(status=status, body={"private error": "synthetic-secret-detail"})
    with pytest.raises(ValueError, match="Paperless read did not succeed") as failure:
        read({})
    assert len(calls) == 1
    assert "synthetic-secret-detail" not in str(failure.value)


@pytest.mark.parametrize(
    "body",
    [
        {"count": True, "results": []},
        {"count": 1, "results": "bad"},
        {"count": 0, "results": [row()]},
        {"count": 1, "results": [row(id="7")]},
        {"count": 1, "results": [row(tags=[True])]},
        {"count": -1, "results": []},
        {"text": "login page"},
    ],
)
def test_malformed_search_payload_never_becomes_evidence(transport, body):
    read, response, calls, _ = transport
    response["body"] = body
    with pytest.raises(ValueError):
        read({})
    assert len(calls) == 1


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "delete", "document_id": 7},
        {"operation": "document", "document_id": 7, "query": "secret"},
        {"operation": "document"},
        {"operation": "document", "document_id": "../7"},
        {"operation": "search", "document_id": 7},
        {"path": "https://outside.example.test"},
        {"query": "bad\nquery"},
        {"limit": 21},
        {"page": 10001},
    ],
)
def test_invalid_read_arguments_rejected_before_dns(transport, arguments):
    read, _, calls, boundaries = transport
    with pytest.raises(ValidationError):
        read(arguments)
    assert not calls and not boundaries


@pytest.mark.parametrize(
    "rules",
    [
        tools.Rules(http_prefixes=["/api/"]),
        tools.Rules(enabled=True, http_prefixes=["/api/"], http_methods=["POST"]),
        tools.Rules(enabled=True, http_prefixes=["/api/tags/"]),
        tools.Rules(enabled=True, http_prefixes=["/api/documents/8/"]),
    ],
)
def test_existing_permissions_rechecked_for_every_concrete_resource(transport, rules):
    read, _, calls, boundaries = transport
    with pytest.raises(PermissionError):
        read({"operation": "document", "document_id": 7}, rules)
    assert not calls and not boundaries


def test_narrow_document_scope_grants_no_search_or_neighbor_document(transport):
    read, response, _, _ = transport
    rules = tools.Rules(enabled=True, http_prefixes=["/api/documents/7/"])
    response["body"] = row()
    assert read({"operation": "document", "document_id": 7}, rules)["data"]["id"] == 7
    with pytest.raises(PermissionError):
        read({"operation": "search"}, rules)
    with pytest.raises(PermissionError):
        read({"operation": "document", "document_id": 70}, rules)


def test_tool_cannot_cross_kind_and_is_readonly_even_with_writes_enabled():
    rules = tools.Rules(enabled=True, http_prefixes=["/api/"], http_methods=["GET", "DELETE"])
    args, effect = tools.validate_tool("paperless", rules, "paperless.read", {})
    assert args["operation"] == "search" and effect is False
    for kind in ("mcp", "home_assistant", "gmail", "ssh", "unifi"):
        with pytest.raises(PermissionError):
            tools.validate_tool(kind, rules, "paperless.read", {})
    profile = SimpleNamespace(kind="paperless", writes_enabled=True)
    assert archive.is_read_profile(profile, rules, CONFIG)
    assert not archive.is_read_profile(profile, rules, {**CONFIG, "kind": "unifi"})


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize("budget", [1400, 2000])
def test_protected_evidence_retains_ids_sources_and_explicit_limits_with_unicode(document, budget):
    large = row(title="漢字" * 150, tags=list(range(1, 513)), content="漢字" * 40000)
    validated = metadata(large, include_content=document)
    result = {
        "label": "LOCAL_ONLY",
        "operation": "document" if document else "search",
        "data": validated
        if document
        else {
            "count": 100,
            "page": 1,
            "page_size": 20,
            "has_next": True,
            "results": [{**validated, "id": i} for i in range(1, 21)],
        },
    }
    original = copy.deepcopy(result)
    view = archive.model_result(result, max_bytes=budget)
    assert len(json.dumps(view, ensure_ascii=False, separators=(",", ":")).encode()) <= budget
    assert view["documents"][0]["id"] == (7 if document else 1)
    assert view["partial_view"] is True
    assert view["model_projection"] == "paperless_query_receipt"
    assert view["full_sha256"] == hashlib.sha256(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if document:
        assert view["documents"][0]["content_truncated"]
    else:
        assert view["omitted"] == 17 and view["has_next"]
    assert result == original


def test_empty_search_is_observed_scoped_not_global_empty():
    result = {
        "label": "LOCAL_ONLY",
        "operation": "search",
        "data": {"count": 0, "page": 1, "page_size": 10, "has_next": False, "results": []},
    }
    view = archive.model_result(result)
    assert view["documents"] == [] and view["count"] == 0
    assert not view["partial_view"]


def test_tool_generation_contract_contains_only_typed_operations():
    rules = tools.Rules(enabled=True, http_prefixes=["/api/"])
    schema = tools.decision_schema(
        ["archive"],
        ["paperless.read"],
        [{"integration_id": "archive", "kind": "paperless", "rules": rules.model_dump()}],
    )
    valid = {
        "kind": "tool",
        "integration_id": "archive",
        "tool": "paperless.read",
        "arguments": {"operation": "search", "query": "Synthetic"},
        "message": "Archiv durchsuchen",
    }
    validate(schema, valid)
    with pytest.raises(ValueError):
        validate(schema, {**valid, "arguments": {"operation": "delete"}})


def test_revocation_at_final_gate_prevents_credential_transmission(transport):
    _, _, calls, boundaries = transport

    def revoked():
        assert boundaries == ["dns"]
        raise PermissionError("Synthetic revoked profile")

    with pytest.raises(PermissionError, match="revoked"):
        tools.invoke(
            Settings(), CONFIG, "synthetic-token", "paperless.read", {},
            tools.Rules(enabled=True, http_prefixes=["/api/"]), revoked,
        )
    assert not calls


def test_unrelated_api_grants_do_not_advertise_archive_tool():
    rules = tools.Rules(enabled=True, http_prefixes=["/api/tags/"])
    schema = tools.decision_schema(
        ["archive"], ["paperless.read"],
        [{"integration_id": "archive", "kind": "paperless", "rules": rules.model_dump()}],
        allow_finish=False,
    )
    with pytest.raises(ValueError):
        validate(schema, {
            "kind": "tool", "integration_id": "archive", "tool": "paperless.read",
            "arguments": {"operation": "search"}, "message": "Read archive",
        })
