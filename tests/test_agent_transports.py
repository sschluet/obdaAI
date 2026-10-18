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
from test_ssh_sftp_write import Authentication, Files, server  # noqa: F401


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
    assert len(checked) >= 3  # Authentication, both commands and optional periodic checks.
    import shutil

    before = (root / "verified.txt").read_bytes()
    metadata = tools.invoke(
        Settings(),
        config,
        "synthetic-secret",
        "ssh.inspect",
        {},
        tools.Rules(enabled=True),
        lambda: checked.append(True),
    )
    assert metadata["exit_code"] == 0
    assert "OBDAAI_COMMAND_AVAILABILITY" in metadata["stdout"]
    capabilities = dict(
        line.split("=", 1) for line in metadata["stdout"].splitlines() if "=" in line
    )
    for name in ["shasum", "sha256sum", "python3"]:
        assert capabilities[name] == (shutil.which(name) or "MISSING")
    assert (root / "verified.txt").read_bytes() == before


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


@pytest.mark.parametrize("path", ["/items/name", "/results/99", "/results/0/id", "/results/no"])
@pytest.mark.parametrize("tool", ["http", "http.verify"])
def test_invalid_get_projection_preserves_response_without_retry_or_verification(
    monkeypatch, path, tool
):
    calls = []
    body = {"results": [{"id": 7, "name": "Synthetic tag"}], "count": 1}

    def reply(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    client = httpx.Client
    monkeypatch.setattr(
        tools.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(reply), **kw)
    )
    monkeypatch.setattr(tools, "pinned_target", lambda *a: ("https://192.168.50.20", {}, {}))
    rules = tools.Rules(enabled=True, http_prefixes=["/api/"])
    request = {"path": "/api/tags/", "projection": {"items_path": path}}
    if tool == "http.verify":
        request.update(effect_step=1, expected={"/body/count": 1})
    args, _ = tools.validate_tool("paperless", rules, tool, request)
    result = tools.invoke(
        Settings(),
        {"url": "https://paperless.example.test", "kind": "paperless"},
        "synthetic-token",
        tool,
        args,
        rules,
        lambda: None,
    )
    assert len(calls) == 1
    assert result["body"] == body and result["http_status"] == 200
    assert result["projection_error"] and result["effect_verified"] is False
    if tool == "http.verify":
        assert result["verification_passed"] is False  # Raw predicate would match.

    args, _ = tools.validate_tool(
        "paperless",
        rules,
        "http",
        {"path": "/api/tags/", "projection": {"items_path": "/results"}},
    )
    corrected = tools.invoke(
        Settings(),
        {"url": "https://paperless.example.test", "kind": "paperless"},
        "synthetic-token",
        "http",
        args,
        rules,
        lambda: None,
    )
    assert len(calls) == 2
    assert corrected["body"]["items"] == body["results"]
    assert "projection_error" not in corrected


def test_projection_recovery_never_catches_write_or_transport_failures(monkeypatch):
    requests = []

    def reply(request):
        requests.append(request)
        if request.method == "GET":
            raise httpx.ConnectError("Synthetic transport failure")
        return httpx.Response(200, json={"results": []})

    client = httpx.Client
    monkeypatch.setattr(
        tools.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(reply), **kw)
    )
    monkeypatch.setattr(tools, "pinned_target", lambda *a: ("https://192.168.50.20", {}, {}))
    rules = tools.Rules(enabled=True, http_prefixes=["/api/"], http_methods=["GET", "POST"])
    for method, error in [("POST", KeyError), ("GET", httpx.ConnectError)]:
        args, _ = tools.validate_tool(
            "paperless",
            rules,
            "http",
            {"method": method, "path": "/api/tags/", "projection": {"items_path": "/wrong"}},
        )
        with pytest.raises(error):
            tools.invoke(
                Settings(),
                {"url": "https://paperless.example.test", "kind": "paperless"},
                "synthetic-token",
                "http",
                args,
                rules,
                lambda: None,
            )
    assert len(requests) == 2


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


@pytest.mark.parametrize(
    ("command_type", "success"),
    [("config/automation/list", True), ("backup/info", True), ("backup/info", False)],
)
def test_native_home_assistant_websocket_authentication_and_command(
    monkeypatch, command_type, success
):
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
        ws.send(
            json.dumps(
                {
                    "id": 1,
                    "type": "result",
                    "success": success,
                    "result": {"ok": True},
                    "error": {"code": "not_supported"},
                }
            )
        )

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
                {"type": command_type, "parameters": {}},
                tools.Rules(enabled=True, ha_websocket_prefixes=["config/", "backup/"]),
                lambda: gates.append(True),
            )
            if success:
                assert result["response"] == {"ok": True}
            else:
                assert result["success"] is False
                assert result["error"] == {"code": "not_supported"}
            assert result["effect_verified"] is False
            assert seen == [
                {"type": "auth", "access_token": "synthetic-ws-token"},
                {"id": 1, "type": command_type},
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


def test_native_sftp_reports_absence_and_hash_without_remote_code(server, monkeypatch):  # noqa: F811
    import hashlib

    config, root = server
    monkeypatch.setattr(Files, "canonicalize", lambda self, path: path)
    (root / "present.txt").write_bytes(b"synthetic")
    rules = tools.Rules(enabled=True, file_read_roots=["/"])
    missing = tools.invoke(
        Settings(),
        config,
        "synthetic-secret",
        "file.read",
        {"path": "/missing.txt"},
        rules,
        lambda: None,
    )
    assert missing["exists"] is False
    found = tools.invoke(
        Settings(),
        config,
        "synthetic-secret",
        "file.read",
        {"path": "/present.txt"},
        rules,
        lambda: None,
    )
    assert found["exists"] is True and found["text"] == "synthetic"
    assert found["sha256"] == hashlib.sha256(b"synthetic").hexdigest()


def test_shell_requires_an_independent_verification_before_creating_intent():
    rules = tools.Rules(enabled=True, shell=True)
    for args in [
        {"script": "echo synthetic"},
        {"script": "echo synthetic", "verification_script": ""},
    ]:
        with pytest.raises(ValueError):
            tools.validate_tool("ssh", rules, "shell", args)


def test_only_exact_existing_ha_metadata_reads_are_classified_as_read_only():
    rules = tools.Rules(enabled=True, ha_websocket_prefixes=["backup/", "supervisor/"])
    calls = [
        ({"type": "backup/info"}, False),
        ({"type": "backup/info", "parameters": {"extra": True}}, True),
        ({"type": "supervisor/api", "parameters": {"endpoint": "/info", "method": "get"}}, False),
        (
            {
                "type": "supervisor/api",
                "parameters": {"endpoint": "/supervisor/info", "method": "get"},
            },
            False,
        ),
        (
            {
                "type": "supervisor/api",
                "parameters": {"endpoint": "/core/update", "method": "post"},
            },
            True,
        ),
        ({"type": "supervisor/api", "parameters": {"endpoint": "/other", "method": "get"}}, True),
        ({"type": "backup/create"}, True),
    ]
    for args, expected_effect in calls:
        assert (
            tools.validate_tool("home_assistant", rules, "ha.websocket", args)[1] is expected_effect
        )


def test_research_generation_requires_bounded_queries_without_extra_keys():
    import jsonschema

    checker = jsonschema.Draft202012Validator(tools.research_schema())
    for queries in [[], ["Official API documentation"], ["a", "b", "c"], ["x" * 500]]:
        checker.validate({"queries": queries})
    for invalid in [
        {".queries": ["Official API documentation"]},
        {"queries": [], "private_observations": "not accepted"},
        {},
        {"queries": ["a", "b", "c", "d"]},
        {"queries": [""]},
        {"queries": ["x" * 501]},
        {"queries": [42]},
        {"queries": "not an array"},
    ]:
        with pytest.raises(jsonschema.ValidationError):
            checker.validate(invalid)


def test_decision_generation_requires_explicit_selected_target_for_every_tool():
    import jsonschema

    schema = tools.decision_schema(["synthetic-selected-target"])
    checker = jsonschema.Draft202012Validator(schema)
    valid = {
        "kind": "tool",
        "integration_id": "synthetic-selected-target",
        "tool": "ssh.inspect",
        "arguments": {},
        "message": "Inspect",
    }
    checker.validate(valid)
    tools.Decision.model_validate(valid)
    for key in ["integration_id", "tool", "arguments"]:
        with pytest.raises(jsonschema.ValidationError):
            checker.validate({k: v for k, v in valid.items() if k != key})
    for target in [None, "other-target", ""]:
        with pytest.raises(jsonschema.ValidationError):
            checker.validate({**valid, "integration_id": target})
    for kind in ["ask", "finish"]:
        checker.validate({"kind": kind, "message": "Synthetic text"})
        with pytest.raises(jsonschema.ValidationError):
            checker.validate({**valid, "kind": kind})
    with pytest.raises(ValueError):
        tools.decision_schema([])
