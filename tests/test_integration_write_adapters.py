"""Pinned transports and fixed external request contracts with synthetic providers."""

import hashlib
import json
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from hub import integration_write_adapters as a
from hub.config import Settings


@pytest.mark.parametrize(
    "kind,operation,args,before,method,path,payload,after",
    [
        (
            "home_assistant",
            "entity.set_power",
            {"entity_id": "light.synthetic", "state": "on"},
            {"entity_id": "light.synthetic", "state": "off"},
            "POST",
            "/api/services/light/turn_on",
            {"entity_id": "light.synthetic"},
            {"entity_id": "light.synthetic", "state": "on"},
        ),
        (
            "home_assistant",
            "entity.set_number",
            {"entity_id": "input_number.synthetic", "value": 42},
            {
                "entity_id": "input_number.synthetic",
                "state": "0",
                "attributes": {"min": 0, "max": 100},
            },
            "POST",
            "/api/services/input_number/set_value",
            {"entity_id": "input_number.synthetic", "value": 42},
            {"entity_id": "input_number.synthetic", "state": "42"},
        ),
        (
            "paperless",
            "document.update_metadata",
            {"document_id": 12, "title": "Synthetic title", "tags": [3, 1, 3]},
            {"id": 12, "title": "Before", "tags": []},
            "PATCH",
            "/api/documents/12/",
            {"title": "Synthetic title", "tags": [1, 3]},
            {"id": 12, "title": "Synthetic title", "tags": [1, 3]},
        ),
        (
            "unifi",
            "guest.set_access",
            {
                "site_id": "11111111-1111-4111-8111-111111111111",
                "client_id": "22222222-2222-4222-8222-222222222222",
                "authorized": True,
            },
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "access": {"type": "GUEST", "authorized": False},
            },
            "POST",
            "/v1/sites/11111111-1111-4111-8111-111111111111/clients/22222222-2222-4222-8222-222222222222/actions",
            {"action": "AUTHORIZE_GUEST_ACCESS", "timeLimitMinutes": 60},
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "access": {
                    "type": "GUEST",
                    "authorized": True,
                    "authorization": {
                        "authorizedAt": "2026-10-17T12:00:00Z",
                        "expiresAt": "2026-10-17T13:00:00Z",
                    },
                },
            },
        ),
    ],
)
def test_pinned_http_operations(
    monkeypatch, kind, operation, args, before, method, path, payload, after
):
    state = dict(before)
    calls = []

    def handle(request):
        assert request.url.host == "192.168.50.9"
        assert request.headers["Host"] == "synthetic.example.test"
        assert request.extensions["sni_hostname"] == "synthetic.example.test"
        assert request.headers["X-API-KEY" if kind == "unifi" else "Authorization"] == (
            "synthetic-key"
            if kind == "unifi"
            else ("Token " if kind == "paperless" else "Bearer ") + "synthetic-key"
        )
        if request.method != "GET":
            calls.append(request)
            assert request.method == method and request.url.path == path
            assert json.loads(request.content) == payload
            state.clear()
            state.update(after)
        return httpx.Response(200, json=state)

    client_class = httpx.Client
    monkeypatch.setattr(
        a.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)
    )
    monkeypatch.setattr(
        a,
        "pinned_target",
        lambda *args: (
            "https://192.168.50.9",
            {"Host": "synthetic.example.test"},
            {"sni_hostname": "synthetic.example.test"},
        ),
    )
    cfg = Settings(integration_targets_enabled=True)
    config = {"kind": kind, "url": "https://synthetic.example.test"}
    args = a.validate_arguments(kind, operation, args)
    a.snapshot(cfg, config, "synthetic-key", operation, args)
    assert not calls
    a.apply(cfg, config, "synthetic-key", operation, args, "synthetic-request")
    current = a.snapshot(cfg, config, "synthetic-key", operation, args)
    assert a.matches(kind, operation, args, current) and len(calls) == 1


def test_http_redirect_never_followed(monkeypatch):
    calls = []
    client_class = httpx.Client

    def handle(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://evil.example.test"})

    monkeypatch.setattr(
        a.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)
    )
    monkeypatch.setattr(
        a,
        "pinned_target",
        lambda *args: ("https://192.168.50.9", {"Host": "synthetic.example.test"}, {}),
    )
    with pytest.raises(ValueError):
        a.request(
            Settings(),
            {"kind": "paperless", "url": "https://synthetic.example.test"},
            "synthetic-key",
            "PATCH",
            "/api/documents/1/",
            {"title": "test"},
        )
    assert len(calls) == 1


class MemoryFile(BytesIO):
    def __init__(self, files, path, mode):
        self.files, self.path, self.mode = files, path, mode
        if "x" in mode and path in files:
            raise FileExistsError(path)
        super().__init__(files.get(path, b""))

    def close(self):
        if not self.closed and ("w" in self.mode or "x" in self.mode):
            self.files[self.path] = self.getvalue()
        super().close()


class MemorySFTP:
    def __init__(self):
        self.files = {}
        self.folder = False
        self.symlink = False

    def normalize(self, path):
        return "/synthetic/home"

    def mkdir(self, path, mode):
        if self.folder:
            raise FileExistsError(path)
        self.folder = True

    def lstat(self, path):
        if path == "/synthetic/home/obdaai-managed":
            if not self.folder:
                raise FileNotFoundError(path)
            return SimpleNamespace(st_mode=0o120777 if self.symlink else 0o40700)
        if path not in self.files:
            raise FileNotFoundError(path)
        return SimpleNamespace(st_mode=0o100600, st_size=len(self.files[path]))

    def open(self, path, mode):
        return MemoryFile(self.files, path, mode)

    def chmod(self, *args):
        pass

    def posix_rename(self, old, new):
        self.files[new] = self.files.pop(old)


def test_sftp_atomic_output_preserves_original_and_rejects_symlink(monkeypatch):
    remote = MemorySFTP()

    @contextmanager
    def connection(*args):
        yield remote

    monkeypatch.setattr(a, "sftp", connection)
    cfg = Settings()
    config = {"kind": "ssh"}
    args = {"filename": "synthetic.txt", "content": "first"}
    assert a.snapshot(cfg, config, "", "file.write_text", args)["exists"] is False
    a.apply(cfg, config, "", "file.write_text", args, "first-action")
    args["content"] = "second"
    a.apply(cfg, config, "", "file.write_text", args, "second-action")
    assert remote.files["/synthetic/home/obdaai-managed/.obdaai-before-second-action"] == b"first"
    state = a.snapshot(cfg, config, "", "file.write_text", args)
    assert state["sha256"] == hashlib.sha256(b"second").hexdigest()
    assert a.matches("ssh", "file.write_text", args, state)
    remote.symlink = True
    with pytest.raises(ValueError):
        a.snapshot(cfg, config, "", "file.write_text", args)


def test_mcp_granted_call_binds_schema_and_rejects_drift(monkeypatch):
    from hub.mcp_client import discover, schema_digest

    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    }
    calls = []

    def handle(req):
        body = json.loads(req.content)
        method = body["method"]
        calls.append(method)
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
        elif method == "notifications/initialized":
            return httpx.Response(202)
        elif method == "tools/list":
            result = {"tools": [{"name": "document.rename", "inputSchema": schema}]}
        elif method == "tools/call":
            assert body["params"] == {
                "name": "document.rename",
                "arguments": {"title": "Synthetic"},
            }
            result = {"content": [{"type": "text", "text": "Done"}]}
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    monkeypatch.setattr(
        "hub.integration_transport.pinned_target",
        lambda *args: ("https://192.168.50.9/mcp", {"Host": "synthetic.example.test"}, {}),
    )
    cfg = Settings(integration_targets_enabled=True)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = discover(
            client,
            cfg,
            "https://synthetic.example.test/mcp",
            "2025-11-25",
            "synthetic-key",
            configured_profile=True,
            granted_tool="document.rename",
            expected_schema=schema_digest(schema),
            granted_arguments={"title": "Synthetic"},
        )
        assert result["acknowledged"] is True and calls.count("tools/call") == 1
        with pytest.raises(ValueError):
            discover(
                client,
                cfg,
                "https://synthetic.example.test/mcp",
                "2025-11-25",
                "synthetic-key",
                configured_profile=True,
                granted_tool="document.rename",
                expected_schema="0" * 64,
                granted_arguments={"title": "Synthetic"},
            )
        assert calls.count("tools/call") == 1


def test_http_final_guard_runs_before_credential_transmission(monkeypatch):
    calls = []
    client_class = httpx.Client

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        a.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)
    )
    monkeypatch.setattr(
        a,
        "pinned_target",
        lambda *args: ("https://192.168.50.9", {"Host": "synthetic.example.test"}, {}),
    )

    def expired():
        raise PermissionError("Grant expired during connection setup")

    with pytest.raises(PermissionError):
        a.apply(
            Settings(),
            {"kind": "paperless", "url": "https://synthetic.example.test"},
            "synthetic-key",
            "document.update_metadata",
            {"document_id": 1, "title": "After"},
            "action-id",
            expired,
        )
    assert not calls
