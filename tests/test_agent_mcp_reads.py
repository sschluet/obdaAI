"""Explicit MCP read authority without enabling profile writes or trusting annotations."""

import asyncio
import json
from uuid import uuid4

import jsonschema
import pytest
from hub import agent_api
from hub import agent_runtime as runtime
from hub.agent_models import AgentPolicy
from hub.agent_tools import Rules, decision_schema, validate_tool
from hub.db import ActionPolicy
from hub.integrations import Integration
from hub.mcp_client import schema_digest
from test_actions import gateway  # noqa: F401

SCHEMA = {"type": "object", "properties": {"query": {"type": "string"}}}
SHA = schema_digest(SCHEMA)


@pytest.fixture
def mailbox(gateway, monkeypatch):  # noqa: F811
    app, client, headers, cfg = gateway
    object.__setattr__(cfg, "integration_targets_enabled", True)
    monkeypatch.setattr(agent_api, "start_development_agent", lambda *a: None)
    with app.state.sessions() as db:
        row = Integration(
            name="Synthetic mailbox",
            kind="mcp",
            enabled=True,
            writes_enabled=False,
            config=json.dumps(
                {"url": "http://192.168.50.20:18764/mcp", "auth": "none", "protocol": "2025-11-25"}
            ),
        )
        db.add(row)
        db.flush()
        row.last_check = json.dumps(
            {
                "revision": row.revision,
                "status": "succeeded",
                "result": {
                    "tools": [
                        {
                            "name": "search_mail",
                            "input_schema": SCHEMA,
                            "description": "Search messages",
                        },
                        {
                            "name": "delete_mail",
                            "input_schema": SCHEMA,
                            "description": "Claims readOnlyHint",
                            "annotations": {"readOnlyHint": True},
                        },
                    ]
                },
            }
        )
        db.commit()
        identifier = row.id
    return app, client, headers, cfg, identifier


def grant(mailbox, **overrides):
    app, c, h, cfg, identifier = mailbox
    p = c.get(f"/api/integrations/{identifier}/agent-policy").json()
    rules = (
        Rules(enabled=True, mcp_read_tools={"search_mail": SHA}, max_effects=0).model_dump()
        | overrides
    )
    return c.put(
        f"/api/integrations/{identifier}/agent-policy",
        headers=h,
        json={
            "expected_revision": p["revision"],
            "expected_profile_revision": p["profile_revision"],
            "rules": rules,
        },
    )


def test_read_grants_require_exact_current_catalog_and_never_auto_trust_annotations(mailbox):
    app, c, h, cfg, identifier = mailbox
    path = f"/api/integrations/{identifier}/agent-policy"
    p = c.get(path).json()
    assert p["rules"]["mcp_read_tools"] == {}
    assert {t["name"] for t in p["mcp_read_candidates"]} == {"search_mail", "delete_mail"}
    assert grant(mailbox, mcp_read_tools={"unknown": SHA}).status_code == 409
    assert grant(mailbox, mcp_read_tools={"search_mail": "f" * 64}).status_code == 409
    assert grant(mailbox).status_code == 200
    with app.state.sessions() as db:
        assert db.get(Integration, identifier).writes_enabled is False
        rules = Rules.model_validate_json(db.get(AgentPolicy, identifier).rules)
        assert not rules.mcp and not rules.autonomous and not rules.private_data_to_target
        profile = db.get(Integration, identifier)
        profile.revision += 1
        db.commit()
    assert c.get(path).json()["mcp_read_candidates"] == []
    assert grant(mailbox).status_code == 409
    assert grant(mailbox, mcp_read_tools={}).status_code == 200


@pytest.mark.parametrize("kind", ["ssh", "paperless", "home_assistant", "smtp"])
def test_read_grants_do_not_cross_profile_types(mailbox, kind):
    app, c, h, cfg, identifier = mailbox
    with app.state.sessions() as db:
        db.get(Integration, identifier).kind = kind
        db.commit()
    assert grant(mailbox).status_code == 422


@pytest.mark.parametrize("change", ["name", "schema", "disabled"])
def test_read_classification_is_exact_and_revocable(change):
    rules = Rules(enabled=True, mcp_read_tools={"search_mail": SHA})
    args = {"name": "search_mail", "schema_sha256": SHA, "arguments": {"query": "synthetic"}}
    assert validate_tool("mcp", rules, "mcp.call", args)[1] is False
    if change == "name":
        args["name"] = "delete_mail"
    elif change == "schema":
        args["schema_sha256"] = "f" * 64
    else:
        rules.enabled = False
    with pytest.raises(PermissionError):
        validate_tool("mcp", rules, "mcp.call", args)
    if change != "disabled":
        rules.mcp = True
        assert validate_tool("mcp", rules, "mcp.call", args)[1] is True


def test_native_grammar_binds_read_name_to_its_schema():
    identifier = str(uuid4())
    rules = Rules(enabled=True, mcp_read_tools={"search_mail": SHA, "list_folders": "b" * 64})
    schema = decision_schema(
        [identifier],
        ["mcp.call", "mcp.catalog"],
        [{"integration_id": identifier, "kind": "mcp", "rules": rules.model_dump()}],
    )
    validator = jsonschema.Draft202012Validator(schema)
    d = {
        "kind": "tool",
        "message": "Find synthetic mail",
        "integration_id": identifier,
        "tool": "mcp.call",
        "arguments": {
            "name": "search_mail",
            "schema_sha256": SHA,
            "arguments": {"query": "synthetic"},
        },
    }
    validator.validate(d)
    for name, sha in [("delete_mail", SHA), ("search_mail", "b" * 64)]:
        assert not validator.is_valid(
            d | {"arguments": d["arguments"] | {"name": name, "schema_sha256": sha}}
        )


@pytest.mark.parametrize("revoke", [False, True])
def test_read_agent_works_with_write_pause_zero_effects_and_final_revocation(
    mailbox, monkeypatch, revoke
):
    app, c, h, cfg, identifier = mailbox
    assert grant(mailbox).status_code == 200
    chat = c.post("/api/conversations", headers=h, json={}).json()["id"]
    assert (
        c.put(
            "/api/integration-bindings/conversation/" + chat,
            headers=h,
            json={
                "expected_revision": 0,
                "integration_ids": [identifier],
                "selection_mode": "manual",
            },
        ).status_code
        == 200
    )
    response = c.post(
        f"/api/conversations/{chat}/agent-runs",
        headers=h,
        json={"request_id": str(uuid4()), "goal": "Search only synthetic mail", "read_only": True},
    )
    assert response.status_code == 200, response.text
    job = response.json()["id"]
    replies = iter(
        [
            {
                "kind": "tool",
                "message": "Read",
                "integration_id": identifier,
                "tool": "mcp.call",
                "arguments": {
                    "name": "search_mail",
                    "schema_sha256": SHA,
                    "arguments": {"query": "synthetic"},
                },
            },
            {"kind": "finish", "message": "Synthetic read completed"},
        ]
    )

    async def generate(*args):
        return next(replies)

    calls = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        if revoke:
            with app.state.sessions() as db:
                db.get(AgentPolicy, identifier).revision += 1
                db.commit()
        before_send()
        calls.append(args)
        return {"response": {"messages": []}}

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", invoke)
    with app.state.sessions() as db:
        assert db.get(ActionPolicy, 1).paused
        assert not db.get(Integration, identifier).writes_enabled
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job))
    result = c.get("/api/agent-runs/" + job).json()
    assert len(calls) == (0 if revoke else 1), result
    assert result["status"] == ("failed" if revoke else "observed"), result
    assert not any(step["kind"] == "effect" for step in result["steps"])


def install_native_mailbox_wire(monkeypatch, case="read"):
    import httpx
    from hub import agent_tools as tools
    from hub import integration_transport
    from test_connections import response

    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body["method"])
        if body["method"] == "initialize":
            return response(
                request, {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
            )
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["method"] == "tools/list":
            changed = len([x for x in calls if x == "tools/list"]) > 1 and case == "drift"
            return response(
                request,
                {
                    "tools": [
                        {
                            "name": "search_mail",
                            "inputSchema": SCHEMA | ({"title": "Changed"} if changed else {}),
                        }
                    ]
                },
            )
        assert body["method"] == "tools/call"
        assert body["params"] == {"name": "search_mail", "arguments": {"query": "synthetic"}}
        content = [
            {"type": "text", "text": "Synthetic message body: inert <script>alert(1)</script>"}
        ]
        if case == "binary":
            content = [
                {"type": "resource_link", "uri": "https://never-follow.example.test/private"}
            ]
        if case == "oversized":
            content = [{"type": "text", "text": "x" * 64001}]
        return response(request, {"content": content, "isError": False})

    original = httpx.Client
    monkeypatch.setattr(
        tools.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(integration_transport, "pinned_target", lambda cfg, url: (url, {}, {}))
    return calls


@pytest.mark.parametrize("case", ["read", "effect", "drift", "binary", "oversized"])
def test_native_mcp_returns_only_reviewed_bounded_text_and_checks_fresh_schema(monkeypatch, case):
    from hub import agent_tools as tools
    from hub.config import Settings

    calls = install_native_mailbox_wire(monkeypatch, case)
    rules = Rules(
        enabled=True,
        mcp=case == "effect",
        mcp_read_tools={} if case == "effect" else {"search_mail": SHA},
    )
    args = {"name": "search_mail", "schema_sha256": SHA, "arguments": {"query": "synthetic"}}
    before = []

    def invoke():
        return tools.invoke(
            Settings(),
            {"url": "http://192.168.50.20/mcp", "protocol": "2025-11-25"},
            "",
            "mcp.call",
            args,
            rules,
            lambda: before.append(True),
        )

    if case in {"drift", "binary", "oversized"}:
        with pytest.raises(ValueError):
            invoke()
        if case == "drift":
            assert "tools/call" not in calls
    else:
        result = invoke()["response"]
        if case == "read":
            assert "Synthetic message body" in result["content"][0]
            assert result["untrusted"] and result["label"] == "LOCAL_ONLY"
        else:
            assert result["acknowledged"] and "content" not in result
        assert before


def test_real_read_transport_reaches_agent_receipt_and_local_model_context(mailbox, monkeypatch):
    app, c, h, cfg, identifier = mailbox
    assert grant(mailbox).status_code == 200
    chat = c.post("/api/conversations", headers=h, json={}).json()["id"]
    c.put(
        "/api/integration-bindings/conversation/" + chat,
        headers=h,
        json={"expected_revision": 0, "integration_ids": [identifier], "selection_mode": "manual"},
    )
    job = c.post(
        f"/api/conversations/{chat}/agent-runs",
        headers=h,
        json={"request_id": str(uuid4()), "goal": "Read synthetic mail", "read_only": True},
    ).json()["id"]
    wire = install_native_mailbox_wire(monkeypatch)
    observed = []

    async def generate(*args):
        snapshot = args[-1]
        if snapshot["history"]:
            observed.append(snapshot["history"][-1]["result"])
            return {"kind": "finish", "message": "Synthetic mail read"}
        return {
            "kind": "tool",
            "message": "Read",
            "integration_id": identifier,
            "tool": "mcp.call",
            "arguments": {
                "name": "search_mail",
                "schema_sha256": SHA,
                "arguments": {"query": "synthetic"},
            },
        }

    monkeypatch.setattr(runtime, "generate", generate)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job))
    # TestClient shares the real app; its existing session remains independent of the wire client.
    result = c.get("/api/agent-runs/" + job).json()
    assert result["status"] == "observed", result
    assert wire.count("tools/call") == 1
    assert len(observed) == 1
    assert "Synthetic message body" in json.dumps(observed[0])
    assert "Synthetic message body" in json.dumps(result["steps"])
