"""Gmail reads stay account-bound, typed and local; model arguments cannot grant rights."""

import json

import httpx
import jsonschema
import pytest
from hub.agent_tools import Rules, decision_schema, invoke, validate_tool
from hub.config import Settings
from hub.gmail_client import API_BASE, GmailClient
from test_actions import gateway  # noqa: F401

TARGET = "00000000-0000-0000-0000-000000000001"


def test_selected_gmail_schema_and_no_write_tool():
    rules = Rules(enabled=True, gmail_read=True, private_data_to_target=True, max_effects=0)
    schema = decision_schema(
        [TARGET],
        ["gmail.read"],
        [
            {
                "integration_id": TARGET,
                "kind": "gmail",
                "rules": rules.model_dump(),
            }
        ],
    )
    decision = {
        "kind": "tool",
        "message": "Search selected mailbox",
        "integration_id": TARGET,
        "tool": "gmail.read",
        "arguments": {"operation": "search", "query": "in:inbox"},
    }
    jsonschema.validate(decision, schema)
    assert validate_tool("gmail", rules, "gmail.read", decision["arguments"])[1] is False
    for changed in [dict(decision, tool="mail.send"), dict(decision, tool="http")]:
        assert not jsonschema.Draft202012Validator(schema).is_valid(changed)


@pytest.mark.parametrize("kind", ["gmail", "mcp", "smtp", "ssh", "paperless"])
def test_no_implicit_or_cross_profile_read_grant(kind):
    with pytest.raises(PermissionError):
        validate_tool(kind, Rules(enabled=True), "gmail.read", {"operation": "labels"})
    if kind != "gmail":
        with pytest.raises(PermissionError):
            validate_tool(
                kind, Rules(enabled=True, gmail_read=True), "gmail.read", {"operation": "labels"}
            )


def test_queries_require_explicit_target_data_permission():
    rules = Rules(enabled=True, gmail_read=True)
    validate_tool("gmail", rules, "gmail.read", {"operation": "message", "message_id": "abc123"})
    with pytest.raises(PermissionError):
        validate_tool(
            "gmail", rules, "gmail.read", {"operation": "search", "query": "private terms"}
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "delete", "message_id": "abc"},
        {"operation": "message", "message_id": "../other"},
        {"operation": "labels", "account": "other@example.test"},
        {"operation": "search", "query": "x\nAuthorization: secret"},
        {"operation": "labels", "query": "unexpected"},
        {"operation": "message"},
        {"operation": "search", "limit": 1000},
    ],
)
def test_invalid_mail_calls_are_rejected(arguments):
    with pytest.raises(ValueError):
        validate_tool(
            "gmail",
            Rules(enabled=True, gmail_read=True, private_data_to_target=True),
            "gmail.read",
            arguments,
        )


def test_invocation_keeps_result_local_and_rechecks_boundary(monkeypatch):
    from hub import gmail_client

    boundary = []
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "gmail.googleapis.com"
        assert request.url.path == "/gmail/v1/users/me/labels"
        assert request.headers["Authorization"] == "Bearer synthetic-access"
        return httpx.Response(200, json={"labels": [{"id": "INBOX", "name": "INBOX"}]})

    original = GmailClient
    monkeypatch.setattr(
        gmail_client,
        "GmailClient",
        lambda token, before_send: original(
            token, transport=httpx.MockTransport(handler), before_send=before_send
        ),
    )
    rules = Rules(enabled=True, gmail_read=True)
    args, _ = validate_tool("gmail", rules, "gmail.read", {"operation": "labels"})
    result = invoke(
        Settings(),
        {"kind": "gmail", "url": API_BASE},
        json.dumps({"access_token": "synthetic-access"}),
        "gmail.read",
        args,
        rules,
        lambda: boundary.append(True),
    )
    assert result["label"] == "LOCAL_ONLY" and boundary and len(calls) == 1
    assert "synthetic-access" not in json.dumps(result)

    def revoked():
        raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        invoke(
            Settings(),
            {"kind": "gmail", "url": API_BASE},
            json.dumps({"access_token": "synthetic-access"}),
            "gmail.read",
            args,
            rules,
            revoked,
        )
    assert len(calls) == 1


@pytest.mark.parametrize("revoke", [False, True])
def test_selected_gmail_agent_dispatch_and_final_revocation(gateway, tmp_path, monkeypatch, revoke):  # noqa: F811
    import asyncio
    import base64
    import time
    from uuid import uuid4

    from hub import agent_api, agent_runtime, gmail_client
    from hub.agent_models import AgentPolicy
    from hub.db import ActionPolicy
    from hub.gmail_setup import MARKER
    from hub.integrations import Integration
    from hub.provider_settings import encrypt

    app, client, headers, cfg = gateway
    key = tmp_path / "synthetic-mail-key"
    key.write_text(base64.b64encode(b"s" * 32).decode())
    key.chmod(0o600)
    object.__setattr__(cfg, "secrets_key_file", str(key))
    object.__setattr__(cfg, "integration_targets_enabled", True)
    monkeypatch.setattr(agent_api, "start_development_agent", lambda *a: None)
    with app.state.sessions() as db:
        profile = Integration(
            name="Aurora synthetic Gmail",
            kind="gmail",
            enabled=True,
            writes_enabled=False,
            config=json.dumps(
                {
                    "url": API_BASE,
                    "auth": "oauth",
                    "gmail_marker": MARKER,
                    "connected": True,
                    "scope": gmail_client.SCOPE,
                    "account_email": "aurora@example.test",
                }
            ),
        )
        db.add(profile)
        db.flush()
        identifier = profile.id
        profile.last_check = json.dumps({"revision": profile.revision, "status": "succeeded"})
        profile.encrypted_secret = encrypt(
            cfg,
            "integration:" + identifier,
            json.dumps(
                {
                    "access_token": "synthetic-access",
                    "refresh_token": "synthetic-refresh",
                    "expires_at": time.time() + 3600,
                    "scope": gmail_client.SCOPE,
                    "token_type": "Bearer",
                    "account_email": "aurora@example.test",
                    "client_id": "synthetic.apps.googleusercontent.com",
                    "client_secret": "synthetic",
                }
            ),
        )
        db.add(
            AgentPolicy(
                integration_id=identifier,
                revision=1,
                profile_revision=profile.revision,
                rules=Rules(
                    enabled=True, gmail_read=True, private_data_to_target=True, max_effects=0
                ).model_dump_json(),
            )
        )
        assert db.get(ActionPolicy, 1).paused
        db.commit()
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    assert (
        client.put(
            "/api/integration-bindings/conversation/" + chat,
            headers=headers,
            json={
                "expected_revision": 0,
                "integration_ids": [identifier],
                "selection_mode": "manual",
            },
        ).status_code
        == 200
    )
    response = client.post(
        f"/api/conversations/{chat}/agent-runs",
        headers=headers,
        json={"request_id": str(uuid4()), "goal": "List labels only", "read_only": True},
    )
    assert response.status_code == 200, response.text
    job = response.json()["id"]
    replies = iter(
        [
            {
                "kind": "tool",
                "message": "Read Gmail labels",
                "integration_id": identifier,
                "tool": "gmail.read",
                "arguments": {"operation": "labels"},
            },
            {"kind": "finish", "message": "Synthetic labels read"},
        ]
    )

    async def generate(*args):
        return next(replies)

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"labels": [{"id": "INBOX", "name": "INBOX"}]})

    original = GmailClient

    def native(token, before_send):
        if revoke:
            with app.state.sessions() as db:
                db.get(AgentPolicy, identifier).revision += 1
                db.commit()
        return original(token, transport=httpx.MockTransport(handler), before_send=before_send)

    monkeypatch.setattr(gmail_client, "GmailClient", native)
    monkeypatch.setattr(agent_runtime, "generate", generate)
    asyncio.run(agent_runtime.execute_agent(app.state.sessions, cfg, None, job))
    result = client.get("/api/agent-runs/" + job).json()
    assert result["status"] == ("failed" if revoke else "observed"), result
    assert len(calls) == (0 if revoke else 1)
    assert not any(step["kind"] == "effect" for step in result["steps"])


def test_gmail_network_plan_is_fixed_and_pending_expiry_bounded(gateway, monkeypatch):  # noqa: F811
    import time

    from hub import integration_transport
    from hub.integrations import Integration

    app, _, _, cfg = gateway
    object.__setattr__(cfg, "integration_targets_enabled", True)
    contacted = []

    def resolve(settings, value, **kwargs):
        contacted.append(value)
        return [("203.0.113.20", 443)]

    monkeypatch.setattr(integration_transport, "resolved_targets", resolve)
    with app.state.sessions() as db:
        row = Integration(
            name="Synthetic pending Gmail",
            kind="gmail",
            enabled=False,
            config=json.dumps(
                {"url": API_BASE, "auth": "oauth", "oauth_pending_until": time.time() + 60}
            ),
        )
        db.add(row)
        db.commit()
        identifier = row.id
    assert len(integration_transport.requests_plan(app.state.sessions, cfg)) == 1
    assert set(contacted) == {API_BASE, "https://oauth2.googleapis.com/token"}
    for config in [
        {"url": API_BASE, "auth": "oauth", "oauth_pending_until": time.time() - 1},
        {
            "url": "https://other.example.test",
            "auth": "oauth",
            "oauth_pending_until": time.time() + 60,
        },
    ]:
        contacted.clear()
        with app.state.sessions() as db:
            db.get(Integration, identifier).config = json.dumps(config)
            db.commit()
        assert integration_transport.requests_plan(app.state.sessions, cfg) == []
        assert contacted == []
