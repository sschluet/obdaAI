"""Bounded MCP HTTP catalog discovery. Remote metadata grants no execution rights."""

import hashlib
import ipaddress
import json
import re
import time
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from hub.config import Settings

VERSIONS = ("2026-07-28", "2025-11-25", "2025-06-18")


MCPFailureReason = Literal[
    "timeout", "remote_tool_error", "response_limit", "schema_changed", "protocol_error"
]


class MCPFailure(ValueError):
    """Safe fixed diagnostic category, without response, URL, argument or secret text."""

    def __init__(self, reason: MCPFailureReason):
        if reason not in {
            "timeout",
            "remote_tool_error",
            "response_limit",
            "schema_changed",
            "protocol_error",
        }:
            raise ValueError("Unknown MCP failure category")
        self.reason = reason
        super().__init__(reason)


class MCPConnectionError(httpx.ConnectError, MCPFailure):
    """Safe connection marker retaining the existing setup ConnectError contract."""

    def __init__(self) -> None:
        super().__init__("protocol_error")


class MCPTransientHTTPError(MCPFailure):
    """Keep the setup-only temporary-HTTP marker; this client never retries requests."""

    def __init__(self, message: str = ""):
        # Existing setup callers may supply a message. Never retain that text.
        super().__init__("protocol_error")


def endpoint(value: str) -> str:
    u = urlsplit(value)
    if (
        u.scheme not in ("https", "http")
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
        or not u.path
        or any(ord(c) < 33 or ord(c) > 126 for c in value)
        or "\\" in value
        or "%" in value
        or u.path.startswith("//")
    ):
        raise ValueError("Invalid MCP endpoint")
    if u.scheme == "http" and u.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Remote MCP requires HTTPS")
    _ = u.port
    return value


def target(cfg: Settings, value: str) -> tuple[str, dict[str, str], dict[str, str]]:
    endpoint(value)
    allowed = json.loads(cfg.mcp_endpoints_json)
    if not isinstance(allowed, dict) or value not in allowed:
        raise ValueError("MCP target not approved by server operator")
    ip = ipaddress.ip_address(allowed[value])
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise ValueError("Forbidden MCP address")
    u = urlsplit(value)
    if u.scheme == "http" and not ip.is_loopback:
        raise ValueError("Unencrypted MCP transport requires loopback address")
    if ip.is_loopback and u.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Remote target mapped to loopback")
    if not ip.is_loopback and not ip.is_global:
        raise ValueError("Private MCP networks require a separate reviewed adapter")
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    port = f":{u.port}" if u.port else ""
    return (
        f"{u.scheme}://{host}{port}{u.path}",
        {"Host": u.netloc},
        {"sni_hostname": u.hostname or ""},
    )


def schema_digest(schema: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def discover(
    client: httpx.Client,
    cfg: Settings,
    url: str,
    version: str,
    token: str,
    *,
    read_tool: str | None = None,
    expected_schema: str = "",
    configured_profile: bool = False,
    granted_tool: str | None = None,
    granted_arguments: dict[str, Any] | None = None,
    granted_read: bool = False,
    before_call: Callable[[], Any] | None = None,
    argument_validator: Callable[[dict[str, Any], Any], None] | None = None,
    before_connect: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    if version not in VERSIONS:
        raise ValueError("Unsupported configured MCP version")
    if granted_read and (not configured_profile or granted_tool is None):
        raise ValueError("MCP read grant requires a configured profile and reviewed tool")
    if configured_profile:
        if read_tool is not None:
            raise ValueError("Profile catalog discovery does not grant execution")
        from hub.integration_transport import pinned_target

        pinned, headers, extensions = pinned_target(cfg, url)
    else:
        if granted_tool is not None:
            raise ValueError("Granted calls require a configured integration profile")
        pinned, headers, extensions = target(cfg, url)
    if before_connect:
        before_connect(urlsplit(pinned).hostname or "")
    if read_tool is not None:
        rules = json.loads(cfg.mcp_read_tools_json)
        if (
            not isinstance(rules, dict)
            or not expected_schema
            or not isinstance(rules.get(url), dict)
            or rules[url].get(read_tool) != expected_schema
        ):
            raise ValueError("MCP read operation not operator approved")
    headers.update(
        {
            "Accept": "application/json, text/event-stream",
            "Accept-Encoding": "identity",
            "MCP-Protocol-Version": version,
        }
    )
    if token:
        if len(token) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in token):
            raise ValueError("Invalid MCP secret")
        headers["Authorization"] = "Bearer " + token
    deadline = time.monotonic() + 20
    sequence = 0

    def _rpc(method: str, params: dict[str, Any], *, notify: bool = False) -> dict[str, Any]:
        nonlocal sequence
        if before_connect:
            before_connect(urlsplit(pinned).hostname or "")
        sequence += 1
        if version == "2026-07-28":
            params = {
                **params,
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": version,
                    "io.modelcontextprotocol/clientInfo": {"name": "obdaAI", "version": "0.1"},
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            }
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            body["id"] = sequence
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MCPFailure("timeout")
        with client.stream(
            "POST",
            pinned,
            headers={**headers, "Mcp-Method": method},
            extensions=extensions,
            json=body,
            follow_redirects=False,
            timeout=min(8, remaining),
        ) as r:
            if r.status_code in (502, 503):
                raise MCPTransientHTTPError()
            if notify:
                if r.status_code not in (200, 202, 204):
                    raise MCPFailure("protocol_error")
                return {}
            if r.status_code != 200:
                raise MCPFailure("protocol_error")
            if r.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise MCPFailure("protocol_error")
            session = r.headers.get("Mcp-Session-Id")
            if session and version != "2026-07-28":
                if not re.fullmatch(r"[\x21-\x7e]{1,200}", session):
                    raise MCPFailure("protocol_error")
                if "Mcp-Session-Id" in headers and headers["Mcp-Session-Id"] != session:
                    raise MCPFailure("protocol_error")
                headers["Mcp-Session-Id"] = session
            payload = bytearray()
            total_bytes = 0
            content_type = r.headers.get("Content-Type", "").split(";")[0].strip()
            for chunk in r.iter_bytes():
                payload.extend(chunk)
                total_bytes += len(chunk)
                if total_bytes > 1_000_000:
                    raise MCPFailure("response_limit")
                if time.monotonic() > deadline:
                    raise MCPFailure("timeout")
                if content_type == "text/event-stream":
                    normalized = bytes(payload).replace(b"\r\n", b"\n")
                    while b"\n\n" in normalized:
                        frame, normalized = normalized.split(b"\n\n", 1)
                        values = [
                            line[5:].lstrip()
                            for line in frame.split(b"\n")
                            if line.startswith(b"data:")
                        ]
                        if not values:
                            continue
                        message = json.loads(b"\n".join(values))
                        if not isinstance(message, dict) or "method" in message:
                            raise MCPFailure("protocol_error")
                        if message.get("id") == sequence:
                            return result(message, call=method == "tools/call")
                    payload = bytearray(normalized)
            if content_type != "application/json":
                raise MCPFailure("protocol_error")
            return result(json.loads(payload), call=method == "tools/call")

    def rpc(method: str, params: dict[str, Any], *, notify: bool = False) -> dict[str, Any]:
        try:
            return _rpc(method, params, notify=notify)
        except httpx.TimeoutException:
            raise MCPFailure("timeout") from None
        except httpx.ConnectError:
            raise MCPConnectionError() from None
        except (httpx.RequestError, json.JSONDecodeError, UnicodeDecodeError):
            raise MCPFailure("protocol_error") from None

    def result(message: Any, *, call: bool = False) -> dict[str, Any]:
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or type(message.get("id")) is not int
            or message["id"] != sequence
            or ("error" not in message and not isinstance(message.get("result"), dict))
        ):
            raise MCPFailure("protocol_error")
        if "error" in message:
            raise MCPFailure("remote_tool_error" if call else "protocol_error")
        data: dict[str, Any] = message["result"]
        if version == "2026-07-28" and data.get("resultType") != "complete":
            raise MCPFailure("protocol_error")
        return data

    if version != "2026-07-28":
        initialized = rpc(
            "initialize",
            {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "obdaAI", "version": "0.1"},
            },
        )
        if (
            initialized.get("protocolVersion") != version
            or not isinstance(initialized.get("capabilities"), dict)
            or "tools" not in initialized["capabilities"]
        ):
            raise MCPFailure("protocol_error")
        rpc("notifications/initialized", {}, notify=True)
    tools: list[dict[str, Any]] = []
    cursor = None
    cursors = set()
    for _ in range(8):
        page = rpc("tools/list", {"cursor": cursor} if cursor else {})
        rows = page.get("tools")
        if not isinstance(rows, list):
            raise MCPFailure("protocol_error")
        for item in rows:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", item["name"])
            ):
                raise MCPFailure("protocol_error")
            schema = item.get("inputSchema")
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise MCPFailure("protocol_error")
            description = item.get("description", "")
            if not isinstance(description, str) or len(description) > 4000:
                raise MCPFailure("protocol_error")
            tools.append(
                {
                    "name": item["name"],
                    "description": description,
                    "input_schema": schema,
                    "execution_allowed": False,
                }
            )
            if len(tools) > 128:
                raise MCPFailure("response_limit")
        cursor = page.get("nextCursor")
        if not cursor:
            break
        if not isinstance(cursor, str) or len(cursor) > 512 or cursor in cursors:
            raise MCPFailure("protocol_error")
        cursors.add(cursor)
    else:
        raise MCPFailure("response_limit")
    if len({t["name"] for t in tools}) != len(tools):
        raise MCPFailure("protocol_error")
    if granted_tool is not None:
        tool = next((t for t in tools if t["name"] == granted_tool), None)
        if not tool or schema_digest(tool["input_schema"]) != expected_schema:
            raise MCPFailure("schema_changed")
        from hub.agent_schema import SchemaValidationFailure
        from hub.integration_write_adapters import validate_mcp_value

        try:
            (argument_validator or validate_mcp_value)(tool["input_schema"], granted_arguments)
        except (MCPFailure, SchemaValidationFailure):
            raise
        except ValueError:
            raise MCPFailure("protocol_error") from None
        if before_call:
            before_call()
        result_data = rpc("tools/call", {"name": granted_tool, "arguments": granted_arguments})
        if result_data.get("isError", False) is not False:
            raise MCPFailure("remote_tool_error")
        if granted_read:
            content = result_data.get("content")
            if not isinstance(content, list) or not 1 <= len(content) <= 16:
                raise MCPFailure("response_limit")
            output = []
            total = 0
            for item in content:
                if (
                    not isinstance(item, dict)
                    or item.get("type") != "text"
                    or not isinstance(item.get("text"), str)
                ):
                    raise MCPFailure("protocol_error")
                total += len(item["text"])
                if total > 64000:
                    raise MCPFailure("response_limit")
                output.append(item["text"])
            return {
                "tool_name": granted_tool,
                "schema_sha256": expected_schema,
                "content": output,
                "label": "LOCAL_ONLY",
                "untrusted": True,
                "automatic_model_context": False,
            }
        return {
            "acknowledged": True,
            "result_sha256": schema_digest(result_data),
            "label": "LOCAL_ONLY",
            "automatic_model_context": False,
        }
    if read_tool is not None:
        tool = next((t for t in tools if t["name"] == read_tool), None)
        if not tool or schema_digest(tool["input_schema"]) != expected_schema:
            raise MCPFailure("schema_changed")
        schema = tool["input_schema"]
        if (
            set(schema)
            - {"type", "properties", "required", "additionalProperties", "title", "description"}
            or schema.get("properties", {}) != {}
            or schema.get("required", []) != []
            or schema.get("additionalProperties") is not False
        ):
            raise ValueError("Only reviewed empty-argument read tools are supported")
        result_data = rpc("tools/call", {"name": read_tool, "arguments": {}})
        if result_data.get("isError", False) is not False:
            raise MCPFailure("remote_tool_error")
        content = result_data.get("content")
        if not isinstance(content, list) or not 1 <= len(content) <= 16:
            raise MCPFailure("response_limit")
        output = []
        total = 0
        for item in content:
            if (
                not isinstance(item, dict)
                or item.get("type") != "text"
                or not isinstance(item.get("text"), str)
            ):
                raise MCPFailure("protocol_error")
            total += len(item["text"])
            if total > 64000:
                raise MCPFailure("response_limit")
            output.append(item["text"])
        return {
            "tool_name": read_tool,
            "schema_sha256": expected_schema,
            "content": output,
            "label": "LOCAL_ONLY",
            "untrusted": True,
            "automatic_model_context": False,
        }
    return {"protocol": version, "tools": tools, "label": "LOCAL_ONLY", "execution_allowed": False}
