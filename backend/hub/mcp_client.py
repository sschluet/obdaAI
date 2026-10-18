"""Bounded MCP HTTP catalog discovery. Remote metadata grants no execution rights."""

import hashlib
import ipaddress
import json
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from hub.config import Settings

VERSIONS = ("2026-07-28", "2025-11-25", "2025-06-18")


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
    before_call: Callable[[], Any] | None = None,
    argument_validator: Callable[[dict[str, Any], Any], None] | None = None,
    before_connect: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    if version not in VERSIONS:
        raise ValueError("Unsupported configured MCP version")
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

    def rpc(method: str, params: dict[str, Any], *, notify: bool = False) -> dict[str, Any]:
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
            raise ValueError("MCP response deadline")
        with client.stream(
            "POST",
            pinned,
            headers={**headers, "Mcp-Method": method},
            extensions=extensions,
            json=body,
            follow_redirects=False,
            timeout=min(8, remaining),
        ) as r:
            if notify:
                if r.status_code not in (200, 202, 204):
                    raise ValueError("MCP notification rejected")
                return {}
            if r.status_code != 200:
                raise ValueError("MCP authentication, version or HTTP failure")
            if r.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Compressed MCP responses unsupported")
            session = r.headers.get("Mcp-Session-Id")
            if session and version != "2026-07-28":
                if not re.fullmatch(r"[\x21-\x7e]{1,200}", session):
                    raise ValueError("Invalid MCP session")
                if "Mcp-Session-Id" in headers and headers["Mcp-Session-Id"] != session:
                    raise ValueError("MCP session changed")
                headers["Mcp-Session-Id"] = session
            payload = bytearray()
            total_bytes = 0
            content_type = r.headers.get("Content-Type", "").split(";")[0].strip()
            for chunk in r.iter_bytes():
                payload.extend(chunk)
                total_bytes += len(chunk)
                if total_bytes > 1_000_000 or time.monotonic() > deadline:
                    raise ValueError("MCP response limit")
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
                            raise ValueError("Server-initiated MCP messages unsupported")
                        if message.get("id") == sequence:
                            return result(message)
                    payload = bytearray(normalized)
            if content_type != "application/json":
                raise ValueError("Unsupported MCP response framing")
            return result(json.loads(payload))

    def result(message: Any) -> dict[str, Any]:
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or type(message.get("id")) is not int
            or message["id"] != sequence
            or "error" in message
            or not isinstance(message.get("result"), dict)
        ):
            raise ValueError("Invalid MCP result")
        data: dict[str, Any] = message["result"]
        if version == "2026-07-28" and data.get("resultType") != "complete":
            raise ValueError("Interactive or incomplete MCP result unsupported")
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
            raise ValueError("MCP protocol/capabilities mismatch")
        rpc("notifications/initialized", {}, notify=True)
    tools: list[dict[str, Any]] = []
    cursor = None
    cursors = set()
    for _ in range(8):
        page = rpc("tools/list", {"cursor": cursor} if cursor else {})
        rows = page.get("tools")
        if not isinstance(rows, list):
            raise ValueError("Invalid MCP catalog")
        for item in rows:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", item["name"])
            ):
                raise ValueError("Invalid MCP tool identity")
            schema = item.get("inputSchema")
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise ValueError("Invalid MCP tool schema")
            description = item.get("description", "")
            if not isinstance(description, str) or len(description) > 4000:
                raise ValueError("Invalid MCP description")
            tools.append(
                {
                    "name": item["name"],
                    "description": description,
                    "input_schema": schema,
                    "execution_allowed": False,
                }
            )
            if len(tools) > 128:
                raise ValueError("MCP catalog limit")
        cursor = page.get("nextCursor")
        if not cursor:
            break
        if not isinstance(cursor, str) or len(cursor) > 512 or cursor in cursors:
            raise ValueError("Invalid MCP pagination")
        cursors.add(cursor)
    else:
        raise ValueError("MCP pagination limit")
    if len({t["name"] for t in tools}) != len(tools):
        raise ValueError("Duplicate MCP tool identity")
    if granted_tool is not None:
        tool = next((t for t in tools if t["name"] == granted_tool), None)
        if not tool or schema_digest(tool["input_schema"]) != expected_schema:
            raise ValueError("MCP granted schema changed")
        from hub.integration_write_adapters import validate_mcp_value

        (argument_validator or validate_mcp_value)(tool["input_schema"], granted_arguments)
        if before_call:
            before_call()
        result_data = rpc("tools/call", {"name": granted_tool, "arguments": granted_arguments})
        if result_data.get("isError", False) is not False:
            raise ValueError("MCP call failed")
        return {
            "acknowledged": True,
            "result_sha256": schema_digest(result_data),
            "label": "LOCAL_ONLY",
            "automatic_model_context": False,
        }
    if read_tool is not None:
        tool = next((t for t in tools if t["name"] == read_tool), None)
        if not tool or schema_digest(tool["input_schema"]) != expected_schema:
            raise ValueError("MCP tool/schema drift")
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
            raise ValueError("MCP tool reported failure")
        content = result_data.get("content")
        if not isinstance(content, list) or not 1 <= len(content) <= 16:
            raise ValueError("MCP read content limit")
        output = []
        total = 0
        for item in content:
            if (
                not isinstance(item, dict)
                or item.get("type") != "text"
                or not isinstance(item.get("text"), str)
            ):
                raise ValueError("Only plain MCP text results are supported")
            total += len(item["text"])
            if total > 64000:
                raise ValueError("MCP text size limit")
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
