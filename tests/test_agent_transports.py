"""Native transport checks, distinct from mocked orchestration and live acceptance."""

import json
import subprocess
import threading

import httpx
import pytest
from hub import agent_tools as tools
from hub.agent_context import fit, project
from hub.agent_schema import validate
from hub.config import Settings
from test_ssh_sftp_write import Authentication, server  # noqa: F401


def test_real_ssh_command_and_separate_verification(server, monkeypatch):  # noqa: F811
    config, root = server
    received = []

    def execute(self, channel, command):
        assert command == b"/bin/sh -s"

        def run():
            with channel.makefile("rb") as stream:
                script = stream.read()
            received.append(script)
            result = subprocess.run(
                ["/bin/sh", "-s"],
                input=script,
                cwd=root,
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.stdout:
                channel.sendall(result.stdout)
            if result.stderr:
                channel.sendall_stderr(result.stderr)
            channel.send_exit_status(result.returncode)
            channel.shutdown_write()

        threading.Thread(target=run, daemon=True).start()
        return True

    monkeypatch.setattr(Authentication, "check_channel_exec_request", execute)
    checked = []
    result = tools.invoke(
        Settings(),
        config,
        "synthetic-secret",
        "shell",
        {
            "script": "printf 'synthetic-native-agent' > verified.txt\n",
            "verification_script": "test \"$(cat verified.txt)\" = 'synthetic-native-agent'\n",
        },
        tools.Rules(enabled=True, shell=True),
        lambda: checked.append(True),
    )
    assert (root / "verified.txt").read_text() == "synthetic-native-agent"
    assert result["effect_verified"] is True
    assert len(received) == 2
    assert len(checked) == 3  # Authentication and both command boundaries.


def test_native_json_schema_supports_local_refs_and_rejects_network_refs():
    schema = {
        "type": "object",
        "$defs": {"text": {"type": "string", "minLength": 2}},
        "properties": {"text": {"$ref": "#/$defs/text"}},
        "required": ["text"],
    }
    validate(schema, {"text": "valid"})
    with pytest.raises(ValueError):
        validate(schema, {"text": "x"})
    with pytest.raises(ValueError):
        validate({"$ref": "https://not-a-permitted-schema.example.test/private"}, {})


def test_schema_regex_does_not_block_parent_process():
    with pytest.raises(ValueError):
        validate({"type": "string", "pattern": "^(a+)+$"}, "a" * 10000 + "!")


def test_http_projection_and_independent_predicate(monkeypatch):
    calls, boundary = [], []

    def reply(request):
        calls.append(request)
        assert boundary
        assert str(request.url).startswith("https://192.168.50.20/api/")
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        return httpx.Response(
            200,
            json=[
                {"entity_id": "light.synthetic", "state": "off"},
                {
                    "entity_id": "update.synthetic",
                    "state": "off",
                    "attributes": {"installed_version": "2.0"},
                },
            ],
        )

    client = httpx.Client
    monkeypatch.setattr(
        tools.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(reply), **kw)
    )
    monkeypatch.setattr(
        tools,
        "pinned_target",
        lambda *a: (
            "https://192.168.50.20",
            {"Host": "ha.example.test"},
            {"sni_hostname": "ha.example.test"},
        ),
    )
    rules = tools.Rules(enabled=True, http_prefixes=["/api/"])
    args, effect = tools.validate_tool(
        "home_assistant",
        rules,
        "http.verify",
        {
            "path": "/api/states",
            "effect_step": 1,
            "projection": {
                "where_pointer": "/entity_id",
                "where_prefix": "update.",
                "fields": ["/entity_id", "/attributes/installed_version"],
            },
            "expected": {"/body/items/0/~1attributes~1installed_version": "2.0"},
        },
    )
    assert effect is False
    result = tools.invoke(
        Settings(),
        {"url": "https://ha.example.test", "kind": "home_assistant"},
        "synthetic-token",
        "http.verify",
        args,
        rules,
        lambda: boundary.append(True),
    )
    assert result["verification_passed"] is True
    assert result["body"]["matched"] == 1
    assert len(calls) == 1


def test_public_target_requires_specific_private_data_grant():
    with pytest.raises(PermissionError):
        tools.private_boundary("8.8.8.8", tools.Rules(enabled=True))
    tools.private_boundary("8.8.8.8", tools.Rules(enabled=True, private_data_to_target=True))
    tools.private_boundary("192.168.50.20", tools.Rules(enabled=True))


def test_context_fit_never_changes_authority_and_keeps_originals():
    original = {
        "goal": "Inspect",
        "interfaces": [{"id": "approved-only"}],
        "tools": {},
        "private_context": [{"text": "s" * 50000}],
        "history": [
            {"kind": "read", "sequence": 1, "document": {}, "result": {"states": "x" * 50000}}
        ],
    }
    result = fit(original, "Fixed instruction", 5000)
    assert result["interfaces"] == original["interfaces"]
    assert len(json.dumps(result)) < 5000
    assert len(original["history"][0]["result"]["states"]) == 50000
    assert result["history"][0]["result"]["truncated"] is True


def test_projection_does_not_execute_selectors():
    with pytest.raises(ValueError):
        project({}, {"items_path": "__import__('os').system('bad')"})


def test_smtp_authority_binds_exact_recipient():
    rules = tools.Rules(enabled=True, mail_recipients=["owner@example.test"])
    args = {
        "recipient": "owner@example.test",
        "subject": "Synthetic report",
        "text": "Only synthetic",
    }
    assert tools.validate_tool("smtp", rules, "mail.send", args)[1] is True
    with pytest.raises(PermissionError):
        tools.validate_tool("smtp", rules, "mail.send", {**args, "recipient": "other@example.test"})


def test_websocket_scope_and_frame_id_are_code_owned():
    rules = tools.Rules(enabled=True, ha_websocket_prefixes=["config/"])
    assert (
        tools.validate_tool(
            "home_assistant",
            rules,
            "ha.websocket",
            {
                "type": "config/entity_registry/list",
                "parameters": {},
            },
        )[1]
        is True
    )
    with pytest.raises(PermissionError):
        tools.validate_tool(
            "home_assistant", rules, "ha.websocket", {"type": "auth/delete_refresh_token"}
        )
    with pytest.raises(ValueError):
        tools.validate_tool(
            "home_assistant",
            rules,
            "ha.websocket",
            {
                "type": "config/entity_registry/list",
                "parameters": {"type": "auth"},
            },
        )


def test_native_home_assistant_websocket_authentication_and_command(monkeypatch):
    import socket

    from websockets.sync.server import serve

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    seen, gates = [], []

    def handler(ws):
        ws.send(json.dumps({"type": "auth_required"}))
        seen.append(json.loads(ws.recv()))
        ws.send(json.dumps({"type": "auth_ok"}))
        seen.append(json.loads(ws.recv()))
        ws.send(json.dumps({"id": 1, "type": "result", "success": True, "result": {"ok": True}}))

    monkeypatch.setattr(tools, "resolved_targets", lambda *a, **kw: [("127.0.0.1", port)])
    with serve(handler, sock=listener) as ws_server:
        thread = threading.Thread(target=ws_server.serve_forever, daemon=True)
        thread.start()
        try:
            result = tools.invoke(
                Settings(),
                {"kind": "home_assistant", "url": "http://ha.example.test"},
                "synthetic-ws-token",
                "ha.websocket",
                {"type": "config/automation/list", "parameters": {}},
                tools.Rules(enabled=True, ha_websocket_prefixes=["config/"]),
                lambda: gates.append(True),
            )
            assert result["response"] == {"ok": True}
            assert result["effect_verified"] is False
            assert seen == [
                {"type": "auth", "access_token": "synthetic-ws-token"},
                {"id": 1, "type": "config/automation/list"},
            ]
            assert len(gates) == 2
        finally:
            ws_server.shutdown()
            thread.join(timeout=3)


def test_multipart_uses_server_bound_original_bytes(monkeypatch):
    seen = []

    def reply(request):
        content = request.read()
        assert b"synthetic-original-binary" in content
        assert b'filename="report.txt"' in content
        assert request.headers["authorization"] == "Token synthetic-token"
        seen.append(content)
        return httpx.Response(202, json={"task_id": "synthetic"})

    client = httpx.Client
    monkeypatch.setattr(
        tools.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(reply), **kw)
    )
    monkeypatch.setattr(
        tools,
        "pinned_target",
        lambda *a: ("https://192.168.50.20", {"Host": "paperless.example.test"}, {}),
    )
    result = tools.invoke(
        Settings(),
        {
            "kind": "paperless",
            "url": "https://paperless.example.test",
            "_upload": ("document", "report.txt", b"synthetic-original-binary"),
            "_upload_fields": {"title": "Synthetic"},
        },
        "synthetic-token",
        "http.upload",
        {"path": "/api/documents/post_document/"},
        tools.Rules(enabled=True, file_upload=True),
        lambda: None,
    )
    assert result["http_status"] == 202 and len(seen) == 1
    assert result["effect_verified"] is False


def test_upload_requires_current_source_binding_and_unchanged_original(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from hub import agent_files

    original = tmp_path / "source"
    original.write_bytes(b"synthetic")
    source = SimpleNamespace(
        id="source", revision=2, sha256="a" * 64, size=9, name="report.txt", status="ready"
    )
    db = SimpleNamespace(get=lambda cls, key: source if key == "source" else None)
    job = SimpleNamespace(context=json.dumps([{"source_id": "source", "revision": 2}]))
    args = {
        "source_id": "source",
        "source_revision": 2,
        "source_sha256": "a" * 64,
        "form_field": "document",
    }
    monkeypatch.setattr(agent_files, "original", lambda *a: original)
    assert agent_files.payload(db, None, job, args) == ("document", "report.txt", b"synthetic")
    with pytest.raises(PermissionError):
        agent_files.check(db, job, {**args, "source_revision": 1})
    with pytest.raises(PermissionError):
        agent_files.check(db, SimpleNamespace(context="[]"), args)
    original.write_bytes(b"changed-size")
    with pytest.raises(ValueError):
        agent_files.payload(db, None, job, args)


def test_read_verification_can_prove_deletion_and_report_missing_rights(monkeypatch):
    client = httpx.Client
    status = [404]
    monkeypatch.setattr(
        tools.httpx,
        "Client",
        lambda **kw: client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(status[0], text="not available")
            ),
            **kw,
        ),
    )
    monkeypatch.setattr(tools, "pinned_target", lambda *a: ("https://192.168.50.20", {}, {}))
    args = {
        "method": "GET",
        "path": "/api/config/automation/config/synthetic",
        "query": {},
        "body": None,
        "expected": {"/http_status": 404},
        "effect_step": 1,
    }
    result = tools.invoke(
        Settings(),
        {"kind": "home_assistant", "url": "https://ha.example.test"},
        "synthetic-token",
        "http.verify",
        args,
        tools.Rules(),
        lambda: None,
    )
    assert result["verification_passed"] is True
    status[0] = 403
    result = tools.invoke(
        Settings(),
        {"kind": "home_assistant", "url": "https://ha.example.test"},
        "synthetic-token",
        "http",
        args,
        tools.Rules(),
        lambda: None,
    )
    assert result["http_status"] == 403
