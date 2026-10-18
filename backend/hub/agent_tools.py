"""Target-bound administration transports; model data cannot select credentials/origins.

Shell authority is the remote account's actual authority, not a working-directory
sandbox. A persisted, explicit policy is required; the model cannot create it.
"""

import copy
import hashlib
import ipaddress
import json
import logging
import re
import socket
import ssl
import time
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from hub.config import Settings
from hub.integration_transport import pinned_target, resolved_targets
from hub.integration_write_adapters import sftp, ssh_client

# Frame-level debug logs must never contain the authentication token.
LOGGER = logging.Logger("hub.agent_transport")
LOGGER.disabled = True

SSH_INSPECT = (
    "/usr/bin/uname -sr\n/usr/bin/id -un\n/usr/bin/uptime\n"
    "if [ -x /usr/bin/sw_vers ]; then /usr/bin/sw_vers; fi\n"
    "printf '\\nOBDAAI_COMMAND_AVAILABILITY\\n'\n"
    "for tool_name in shasum sha256sum openssl python3 base64 systemctl launchctl docker ha; do\n"
    '  resolved=$(command -v "$tool_name" 2>/dev/null || true)\n'
    '  printf \'%s=%s\\n\' "$tool_name" "${resolved:-MISSING}"\n'
    "done\n"
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def api_path(value: str) -> str:
    if (
        not value.startswith("/")
        or value.startswith("//")
        or any(
            c not in "/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.~-"
            for c in value
        )
        or any(p in {".", ".."} for p in value.split("/"))
        or "//" in value
    ):
        raise ValueError("Only a plain path within the registered API is accepted")
    return value


class Rules(Strict):
    enabled: bool = False
    autonomous: bool = False
    private_data_to_target: bool = False
    file_upload: bool = False
    http_prefixes: list[str] = Field(default_factory=list, max_length=16)
    http_methods: list[Literal["GET", "POST", "PUT", "PATCH", "DELETE"]] = Field(
        default=["GET"], max_length=5
    )
    shell: bool = False
    home_assistant_host: bool = False
    production_ha_approved: bool = False
    ha_websocket_prefixes: list[str] = Field(default_factory=list, max_length=30)
    mcp: bool = False
    mail_recipients: list[str] = Field(default_factory=list, max_length=50)
    file_read_roots: list[str] = Field(default_factory=list, max_length=16)
    max_steps: int = Field(default=20, ge=1, le=80)
    max_effects: int = Field(default=5, ge=0, le=20)
    max_research_queries: int = Field(default=6, ge=0, le=30)
    timeout_seconds: int = Field(default=600, ge=30, le=3600)
    command_timeout_seconds: int = Field(default=60, ge=1, le=600)

    @model_validator(mode="after")
    def paths(self) -> "Rules":
        from hub.smtp_client import mailbox

        for address in self.mail_recipients:
            mailbox(address)
        if any(not re.fullmatch(r"[a-z][a-z0-9_/]*", p) for p in self.ha_websocket_prefixes):
            raise ValueError("Invalid Home Assistant WebSocket command scope")
        for path in self.http_prefixes:
            api_path(path)
            if not path.endswith("/"):
                raise ValueError("API scopes must end in a slash")
        for path in self.file_read_roots:
            if (
                not path.startswith("/")
                or "\x00" in path
                or any(p in {".", ".."} for p in path.split("/"))
            ):
                raise ValueError("Absolute file roots without traversal required")
        return self


class Projection(Strict):
    items_path: str = Field(default="", max_length=1000)
    where_pointer: str | None = Field(default=None, max_length=1000)
    where_equals: Any = None
    where_prefix: str | None = Field(default=None, max_length=200)
    fields: list[str] = Field(default_factory=list, max_length=32)
    limit: int = Field(default=30, ge=1, le=100)


class ResearchCall(Strict):
    topic: Literal["interfaces", "updates", "configuration", "backup", "troubleshooting"]


JSONPointer = Annotated[str, Field(pattern=r"^/")]
APIPath = Annotated[str, Field(pattern=r"^/[A-Za-z0-9_.~/-]*$", min_length=1, max_length=1000)]


class ReadVerification(Strict):
    path: APIPath
    query: dict[str, str | int | bool] = Field(default_factory=dict, max_length=30)
    expected: dict[JSONPointer, Any] = Field(min_length=1, max_length=32)
    timeout_seconds: int = Field(default=300, ge=1, le=900)
    interval_seconds: int = Field(default=5, ge=1, le=30)

    @model_validator(mode="after")
    def validate_path(self) -> "ReadVerification":
        api_path(self.path)
        if len(json.dumps(self.model_dump(), allow_nan=False)) > 32000:
            raise ValueError("Verification limit")
        return self


class HTTPCall(Strict):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: APIPath
    query: dict[str, str | int | bool] = Field(default_factory=dict, max_length=30)
    body: dict[str, Any] | list[Any] | None = None
    projection: Projection | None = None
    verification: ReadVerification | None = None

    @model_validator(mode="after")
    def validate_path(self) -> "HTTPCall":
        api_path(self.path)
        if self.method == "GET" and self.body is not None:
            raise ValueError("Reads must not have a request body")
        if self.method == "GET" and self.verification is not None:
            raise ValueError("Reads cannot contain an effect verification loop")
        if len(json.dumps(self.model_dump(), allow_nan=False).encode()) > 200_000:
            raise ValueError("Request too large")
        return self


class ShellCall(Strict):
    script: str = Field(min_length=1, max_length=64000)
    verification_script: str = Field(min_length=1, max_length=16000)


class HTTPVerify(HTTPCall):
    method: Literal["GET"] = "GET"
    effect_step: int = Field(ge=1)
    expected: dict[JSONPointer, Any] = Field(min_length=1, max_length=32)


class FileRead(Strict):
    path: str = Field(min_length=1, max_length=1000)


class MCPCall(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    arguments: dict[str, Any]


class UploadCall(Strict):
    path: APIPath
    source_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_revision: int = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    form_field: str = Field(default="document", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,60}$")
    fields: dict[str, str] = Field(default_factory=dict, max_length=30)
    verification: ReadVerification | None = None

    @model_validator(mode="after")
    def target(self) -> "UploadCall":
        api_path(self.path)
        if len(json.dumps(self.fields)) > 16000:
            raise ValueError("Multipart metadata limit")
        return self


class HACall(Strict):
    type: str = Field(pattern=r"^[a-z][a-z0-9_/]{0,150}$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    verification: ReadVerification | None = None

    @model_validator(mode="after")
    def envelope(self) -> "HACall":
        if {"id", "type"} & self.parameters.keys() or len(
            json.dumps(self.parameters, allow_nan=False)
        ) > 200000:
            raise ValueError("Invalid WebSocket command parameters")
        return self


class MailCall(Strict):
    recipient: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=200, pattern=r"^[^\r\n\x00]+$")
    text: str = Field(min_length=1, max_length=100000)


class Decision(Strict):
    kind: Literal["tool", "finish", "ask"]
    message: str = Field(min_length=1, max_length=4000)
    integration_id: str | None = None
    tool: (
        Literal[
            "http",
            "http.verify",
            "shell",
            "file.read",
            "mcp.catalog",
            "mcp.call",
            "research",
            "mail.send",
            "ha.websocket",
            "ssh.inspect",
            "http.upload",
        ]
        | None
    ) = None
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def shape(self) -> "Decision":
        if self.kind == "tool":
            if not self.integration_id or not self.tool:
                raise ValueError("Tool decision needs a selected integration")
        elif self.integration_id is not None or self.tool is not None or self.arguments:
            raise ValueError("Text decisions cannot carry tools")
        return self


def research_schema() -> dict[str, Any]:
    """Constrain public query planning without repairing generated keys."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["queries"],
        "properties": {
            "queries": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
            }
        },
    }


def decision_envelope_schema(
    integration_ids: Sequence[str], tool_names: Sequence[str] | None = None
) -> dict[str, Any]:
    """Compact prompt contract; full typed arguments live in tools and native grammar."""
    if not integration_ids:
        raise ValueError("Decision generation requires selected targets")
    names = sorted(SCHEMAS if tool_names is None else set(tool_names))
    if any(name not in SCHEMAS for name in names):
        raise ValueError("Unknown administration tool in generation schema")
    message = Decision.model_json_schema()["properties"]["message"]
    branches = []
    if names:
        branches.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string", "const": "tool"},
                    "message": message,
                    "integration_id": {"type": "string", "enum": sorted(set(integration_ids))},
                    "tool": {"type": "string", "enum": names},
                    "arguments": {"type": "object"},
                },
                "required": ["kind", "message", "integration_id", "tool", "arguments"],
            }
        )
    branches.append(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {"type": "string", "enum": ["ask", "finish"]},
                "message": message,
            },
            "required": ["kind", "message"],
        }
    )
    return {"type": "object", "anyOf": branches}


def _interface_rules(
    integration_ids: Sequence[str], interfaces: Sequence[dict[str, Any]]
) -> list[tuple[str, str, Rules]]:
    selected = set(integration_ids)
    found: set[str] = set()
    result = []
    for interface in interfaces:
        if not isinstance(interface, dict):
            raise ValueError("Invalid bound administration interfaces")
        identifier = interface.get("integration_id")
        kind = interface.get("kind")
        if (
            not isinstance(identifier, str)
            or identifier not in selected
            or identifier in found
            or not isinstance(kind, str)
            or kind not in {"ssh", "home_assistant", "paperless", "unifi", "mcp", "smtp"}
            or not isinstance(interface.get("rules"), dict)
        ):
            raise ValueError("Invalid bound administration interfaces")
        rules = Rules.model_validate(interface["rules"])
        found.add(identifier)
        result.append((identifier, kind, rules))
    if found != selected:
        raise ValueError("Missing bound administration interfaces")
    return result


def _interface_tool(kind: str, rules: Rules, tool: str) -> bool:
    if not rules.enabled:
        return False
    if tool == "research":
        return True
    if tool in {"http", "http.verify", "http.upload"}:
        if kind not in {"home_assistant", "paperless", "unifi"} or not rules.http_prefixes:
            return False
        if tool == "http":
            return bool(rules.http_methods)
        if tool == "http.verify":
            return "GET" in rules.http_methods
        return rules.file_upload and "POST" in rules.http_methods
    if tool == "ha.websocket":
        return kind == "home_assistant" and bool(rules.ha_websocket_prefixes)
    if tool == "mail.send":
        return kind == "smtp" and bool(rules.mail_recipients)
    if tool in {"mcp.call", "mcp.catalog"}:
        return kind == "mcp" and rules.mcp
    if tool == "ssh.inspect":
        return kind == "ssh"
    if tool == "shell":
        return kind == "ssh" and rules.shell
    if tool == "file.read":
        return kind == "ssh" and (rules.shell or bool(rules.file_read_roots))
    return False


def _scoped_arguments(tool: str, schema: dict[str, Any], rules: Rules) -> dict[str, Any]:
    result = copy.deepcopy(schema)
    path_pattern = (
        "^(?:" + "|".join(re.escape(p) for p in rules.http_prefixes) + ")[A-Za-z0-9_.~/-]*$"
    )
    variants = result.get("anyOf", [result]) if tool == "http" else [result]
    retained = []
    for variant in variants:
        properties = variant["properties"]
        if tool in {"http", "http.verify"}:
            method = properties["method"]
            allowed = [
                value
                for value in method.get("enum", [method.get("const")])
                if value in rules.http_methods
            ]
            if not allowed:
                continue
            properties["method"] = {"type": "string", "enum": allowed}
        if tool in {"http", "http.verify", "http.upload"}:
            properties["path"]["pattern"] = path_pattern
        if tool == "ha.websocket":
            alternatives = [
                re.escape(prefix) + ("[a-z0-9_/]*" if prefix.endswith("/") else "")
                for prefix in rules.ha_websocket_prefixes
            ]
            properties["type"]["pattern"] = "^(?:" + "|".join(alternatives) + ")$"
            properties["type"]["maxLength"] = 151
        if tool == "mail.send":
            properties["recipient"]["enum"] = rules.mail_recipients
        if "verification" in properties and properties["verification"].get("type") != "null":
            if "GET" not in rules.http_methods or not rules.http_prefixes:
                properties["verification"] = {"type": "null"}
            else:
                verification = ReadVerification.model_json_schema()
                verification["properties"]["path"]["pattern"] = path_pattern
                verification["properties"]["expected"]["additionalProperties"] = False
                properties["verification"] = {"anyOf": [verification, {"type": "null"}]}
        retained.append(variant)
    if not retained:
        raise ValueError("No allowed administration argument variant")
    return {"anyOf": retained} if tool == "http" else retained[0]


def decision_schema(
    integration_ids: Sequence[str],
    tool_names: Sequence[str] | None = None,
    interfaces: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Constrain generation to typed, available tools; runtime gates remain authoritative."""
    envelope = decision_envelope_schema(integration_ids, tool_names)
    names = sorted(SCHEMAS if tool_names is None else set(tool_names))
    bound = _interface_rules(integration_ids, interfaces) if interfaces is not None else None
    definitions: dict[str, Any] = {}
    branches: list[dict[str, Any]] = []
    for name in names:
        model = SCHEMAS[name]
        arguments = model.model_json_schema()
        for key, definition in arguments.pop("$defs", {}).items():
            if key in definitions and definitions[key] != definition:
                raise ValueError("Conflicting administration schema definitions")
            definitions[key] = definition
        if issubclass(model, HTTPCall):
            properties = arguments["properties"]
            required = list(dict.fromkeys([*arguments.get("required", []), "method"]))
            read = {
                **arguments,
                "properties": {
                    **properties,
                    "method": {"type": "string", "const": "GET"},
                    "body": {"type": "null"},
                    "verification": {"type": "null"},
                },
                "required": required,
            }
            if model is HTTPVerify:
                arguments = read
            else:
                write = {
                    **arguments,
                    "properties": {
                        **properties,
                        "method": {"type": "string", "enum": ["POST", "PUT", "PATCH", "DELETE"]},
                    },
                    "required": required,
                }
                arguments = {"anyOf": [read, write]}
        targets = (
            [(None, None)]
            if bound is None
            else [
                (identifier, rules)
                for identifier, kind, rules in bound
                if _interface_tool(kind, rules, name)
            ]
        )
        for index, (identifier, rules) in enumerate(targets):
            definition_name = "Tool_" + name.replace(".", "_")
            if identifier is not None:
                definition_name += "_" + str(index)
            definitions[definition_name] = (
                arguments if rules is None else _scoped_arguments(name, arguments, rules)
            )
            branch = envelope["anyOf"][0]
            properties = {
                **branch["properties"],
                "tool": {"type": "string", "const": name},
                "arguments": {"$ref": "#/$defs/" + definition_name},
            }
            if identifier is not None:
                properties["integration_id"] = {"type": "string", "const": identifier}
            branches.append({**branch, "properties": properties})
    # Pydantic emits patternProperties for constrained dictionary keys, which alone
    # allows nonmatching keys in JSON Schema. Match the actual pointer validator.
    for definition in definitions.values():
        expected = definition.get("properties", {}).get("expected")
        if expected is not None:
            expected["additionalProperties"] = False
    branches.append(envelope["anyOf"][-1])
    return {"type": "object", "$defs": definitions, "anyOf": branches}


SCHEMAS: dict[str, type[Strict]] = {
    "ssh.inspect": Strict,
    "mcp.catalog": Strict,
    "http.upload": UploadCall,
    "ha.websocket": HACall,
    "mail.send": MailCall,
    "research": ResearchCall,
    "http": HTTPCall,
    "http.verify": HTTPVerify,
    "shell": ShellCall,
    "file.read": FileRead,
    "mcp.call": MCPCall,
}


def ha_metadata_read(data: dict[str, Any]) -> bool:
    """Only the installation/backup reads already used by the fixed HA reader."""
    parameters = data["parameters"]
    return (data["type"] == "backup/info" and not parameters) or (
        data["type"] == "supervisor/api"
        and set(parameters) == {"endpoint", "method"}
        and parameters["method"] == "get"
        and parameters["endpoint"] in {"/info", "/supervisor/info"}
    )


def validate_tool(
    kind: str, rules: Rules, tool: str, arguments: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Return normalized inert data and effect classification, independent of model claims."""
    if not rules.enabled:
        raise PermissionError("Agent administration is disabled")
    if tool == "mcp.catalog" and kind == "mcp" and rules.mcp and not arguments:
        return {}, False
    model = SCHEMAS.get(tool)
    if model is None:
        raise ValueError("Unknown administration tool")
    data = model.model_validate(arguments).model_dump()
    if data.get("verification"):
        proof = data["verification"]
        validate_tool(
            kind,
            rules,
            "http.verify",
            {
                "path": proof["path"],
                "query": proof["query"],
                "expected": proof["expected"],
                "effect_step": 1,
            },
        )
    if tool == "research":
        return data, False
    if tool == "ssh.inspect" and kind == "ssh":
        return data, False
    if tool == "http.upload" and kind in {"home_assistant", "paperless", "unifi"}:
        if (
            rules.file_upload
            and "POST" in rules.http_methods
            and any(data["path"].startswith(prefix) for prefix in rules.http_prefixes)
        ):
            return data, True
        raise PermissionError("Original file transfer is not authorized")
    if tool == "mail.send" and kind == "smtp" and data["recipient"] in rules.mail_recipients:
        return data, True
    if (
        tool == "ha.websocket"
        and kind == "home_assistant"
        and any(
            data["type"].startswith(p) if p.endswith("/") else data["type"] == p
            for p in rules.ha_websocket_prefixes
        )
    ):
        read = ha_metadata_read(data)
        if read and data["verification"] is not None:
            raise ValueError("Metadata reads cannot carry effect verification")
        return data, not read  # Unknown WebSocket commands can have effects.
    if tool in {"http", "http.verify"}:
        if kind not in {"home_assistant", "paperless", "unifi"}:
            raise PermissionError("No HTTP administration interface for this profile")
        if data["method"] not in rules.http_methods or not any(
            data["path"].startswith(prefix) for prefix in rules.http_prefixes
        ):
            raise PermissionError("API operation is outside the approved rules")
        return data, data["method"] != "GET"
    if tool == "shell" and kind == "ssh" and rules.shell:
        return data, True  # Even commands claiming to be a read are potentially effective.
    if tool == "file.read" and kind == "ssh":
        path = data["path"]
        if "\x00" in path or any(p in {".", ".."} for p in path.split("/")):
            raise ValueError("Invalid file path")
        if path.startswith("/") and (
            rules.shell
            or any(
                path == root.rstrip("/") or path.startswith(root.rstrip("/") + "/")
                for root in rules.file_read_roots
            )
        ):
            return data, False
    if tool == "mcp.call" and kind == "mcp" and rules.mcp:
        return data, True  # Annotations do not confer read authority.
    raise PermissionError("Interface is outside the approved administration rules")


def http_call(
    cfg: Settings,
    config: dict[str, Any],
    secret: str,
    args: dict[str, Any],
    before_send: Callable[[], Any],
    rules: Rules,
) -> dict[str, Any]:
    base = config["url"].rstrip("/")
    if config["kind"] == "paperless" and base.endswith("/api"):
        base = base[:-4]
    pinned, headers, extensions = pinned_target(cfg, base)
    private_boundary(urlsplit(pinned).hostname or "", rules)
    if not secret or len(secret) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in secret):
        raise ValueError("Invalid integration credential")
    if config["kind"] == "unifi":
        headers["X-API-KEY"] = secret
    else:
        headers["Authorization"] = (
            "Token " if config["kind"] == "paperless" else "Bearer "
        ) + secret
    headers.update({"Accept": "application/json", "Accept-Encoding": "identity"})
    with httpx.Client(verify=True, trust_env=False, follow_redirects=False, timeout=25) as client:
        before_send()  # AFTER DNS/setup, before any credential-bearing transmission.
        payload: dict[str, Any] = {"json": args["body"]}
        if config.get("_upload"):
            field, filename, content = config["_upload"]
            payload = {
                "files": {field: (filename, content, "application/octet-stream")},
                "data": config["_upload_fields"],
            }
        with client.stream(
            args["method"],
            pinned.rstrip("/") + args["path"],
            params=args["query"],
            **payload,
            headers=headers,
            extensions=extensions,
        ) as response:
            if args["method"] != "GET" and not 200 <= response.status_code < 300:
                raise ValueError("Administration API did not acknowledge the request")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("Compressed response unsupported")
            data = bytearray()
            deadline = time.monotonic() + 30
            for chunk in response.iter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > 8_000_000 or time.monotonic() > deadline:
                    raise ValueError("Administration response limit")
            try:
                body = json.loads(data) if data else {}
            except ValueError:
                if args["method"] != "GET":
                    raise
                body = {"text": data.decode("utf-8", errors="replace")}
            projection_error = False
            if args.get("projection"):
                from hub.agent_context import project

                try:
                    body = project(body, args["projection"])
                except (KeyError, IndexError, TypeError, ValueError):
                    if args["method"] != "GET":
                        raise
                    projection_error = True
            return {
                "http_status": response.status_code,
                "body": body,
                "effect_verified": False,
                **(
                    {
                        "projection_error": "Auswahl passt nicht zur Antwortstruktur; "
                        "body enthält die unveränderte Antwort."
                    }
                    if projection_error
                    else {}
                ),
            }


def command(
    client: Any, script: str, timeout: int, before_send: Callable[[], Any]
) -> dict[str, Any]:
    transport = client.get_transport()
    if transport is None:
        raise ValueError("SSH transport unavailable")
    with transport.open_session(timeout=8) as channel:
        channel.settimeout(8)
        before_send()
        channel.exec_command("/bin/sh -s")
        channel.sendall(script.encode())
        channel.shutdown_write()
        out, err = bytearray(), bytearray()
        deadline = time.monotonic() + timeout
        checked = time.monotonic()
        while True:
            if time.monotonic() - checked >= 0.5:
                before_send()  # Notice cancellation/expiry while waiting; no retransmission.
                checked = time.monotonic()
            if channel.recv_ready():
                out.extend(channel.recv(32768))
            if channel.recv_stderr_ready():
                err.extend(channel.recv_stderr(32768))
            if len(out) + len(err) > 200_000 or time.monotonic() >= deadline:
                raise TimeoutError("SSH result uncertain; remote process may still be running")
            if (
                channel.exit_status_ready()
                and not channel.recv_ready()
                and not channel.recv_stderr_ready()
            ):
                break
            time.sleep(0.01)
        return {
            "exit_code": channel.recv_exit_status(),
            "stdout": out.decode(errors="replace"),
            "stderr": err.decode(errors="replace"),
        }


def private_boundary(address: str, rules: Rules) -> None:
    if ipaddress.ip_address(address).is_global and not rules.private_data_to_target:
        raise PermissionError("Private Agentendaten für dieses öffentliche Ziel nicht freigegeben")


def invoke(
    cfg: Settings,
    config: dict[str, Any],
    secret: str,
    tool: str,
    args: dict[str, Any],
    rules: Rules,
    before_send: Callable[[], Any],
) -> dict[str, Any]:
    def credential_boundary(address: str) -> None:
        private_boundary(address, rules)
        before_send()

    if tool == "ssh.inspect":
        with ssh_client(cfg, config, secret, credential_boundary) as client:
            return command(
                client,
                SSH_INSPECT,
                10,
                before_send,
            )

    if tool == "ha.websocket":
        from websockets.sync.client import connect as websocket_connect

        url = config["url"].rstrip("/")
        parsed = urlsplit(url)
        address, port = resolved_targets(cfg, url)[0]
        private_boundary(address, rules)
        uri = (
            ("wss" if parsed.scheme == "https" else "ws") + url[url.index(":") :] + "/api/websocket"
        )
        sock = socket.create_connection((address, port), timeout=8)
        try:
            options: dict[str, Any] = {
                "sock": sock,
                "proxy": None,
                "compression": None,
                "open_timeout": 8,
                "close_timeout": 2,
                "max_size": 8_000_000,
                "logger": LOGGER,
            }
            if parsed.scheme == "https":
                options.update(ssl=ssl.create_default_context(), server_hostname=parsed.hostname)
            with websocket_connect(uri, **options) as connection:
                if json.loads(connection.recv(timeout=15)).get("type") != "auth_required":
                    raise ValueError("Unexpected HA authentication handshake")
                before_send()
                connection.send(json.dumps({"type": "auth", "access_token": secret}))
                if json.loads(connection.recv(timeout=15)).get("type") != "auth_ok":
                    raise ValueError("HA WebSocket authentication failed")
                before_send()
                connection.send(json.dumps({"id": 1, "type": args["type"], **args["parameters"]}))
                for _ in range(20):
                    result = json.loads(connection.recv(timeout=25))
                    if result.get("id") == 1 and result.get("type") == "result":
                        if result.get("success") is not True:
                            if ha_metadata_read(args):
                                return {
                                    "success": False,
                                    "error": result.get("error"),
                                    "effect_verified": False,
                                }
                            raise ValueError("HA did not acknowledge the command")
                        return {"response": result.get("result"), "effect_verified": False}
                raise ValueError("HA WebSocket response limit")
        finally:
            sock.close()
        raise ValueError("HA WebSocket closed without a result")
    if tool == "http.upload":
        return http_call(
            cfg,
            config,
            secret,
            {"method": "POST", "path": args["path"], "query": {}, "body": None},
            before_send,
            rules,
        )
    if tool == "mail.send":
        from email.message import EmailMessage

        from hub.smtp_client import connect, mailbox, send

        message = EmailMessage()
        message["From"] = mailbox(config["sender"])
        message["To"] = mailbox(args["recipient"])
        message["Subject"] = args["subject"]
        message.set_content(args["text"])
        with connect(cfg, config, secret, credential_boundary) as connection:
            if connection.sock is None:
                raise ValueError("SMTP socket unavailable")
            private_boundary(connection.sock.getpeername()[0], rules)
            before_send()
            send(connection, message, before_send)
        return {"smtp_accepted": True, "delivery_verified": False, "effect_verified": False}
    if tool in {"http", "http.verify"}:
        response = http_call(cfg, config, secret, args, before_send, rules)
        if tool == "http.verify":
            response["verification_passed"] = not response.get("projection_error")
            for pointer, expected in args["expected"].items():
                if not pointer.startswith("/"):
                    raise ValueError("Verification needs JSON pointers")
                value: Any = response
                try:
                    for key in pointer[1:].split("/"):
                        key = key.replace("~1", "/").replace("~0", "~")
                        value = value[int(key)] if isinstance(value, list) else value[key]
                    if type(value) is not type(expected) or value != expected:
                        response["verification_passed"] = False
                except (KeyError, IndexError, TypeError, ValueError):
                    response["verification_passed"] = False
        return response
    if tool == "shell":
        with ssh_client(cfg, config, secret, credential_boundary) as client:
            private_boundary(client.get_transport().sock.getpeername()[0], rules)
            result = command(client, args["script"], rules.command_timeout_seconds, before_send)
            result["effect_verified"] = False
            if result["exit_code"] == 0 and args["verification_script"]:
                result["verification"] = command(
                    client, args["verification_script"], rules.command_timeout_seconds, before_send
                )
                result["effect_verified"] = result["verification"]["exit_code"] == 0
                result["verification_method"] = "agent_defined_remote_script"
                result["causation_verified"] = False
            return result
    if tool == "file.read":
        import stat

        with sftp(cfg, config, secret, credential_boundary) as remote:
            private_boundary(remote.get_channel().get_transport().sock.getpeername()[0], rules)
            before_send()
            # A symlink inside a permitted root must not escape that root.
            canonical = remote.normalize(args["path"])
            validate_tool("ssh", rules, "file.read", {"path": canonical})
            before_send()
            try:
                attrs = remote.stat(canonical)
            except FileNotFoundError:
                return {"path": canonical, "exists": False}
            if not stat.S_ISREG(attrs.st_mode) or attrs.st_size > 200_000:
                raise ValueError("Not a bounded regular text file")
            with remote.open(canonical, "rb") as handle:
                data = handle.read(200_001)
            if len(data) > 200_000:
                raise ValueError("File grew beyond the limit")
            return {
                "path": canonical,
                "exists": True,
                "sha256": hashlib.sha256(data).hexdigest(),
                "text": data.decode("utf-8"),
            }
    if tool in {"mcp.catalog", "mcp.call"}:
        from hub.agent_schema import validate
        from hub.mcp_client import discover, schema_digest

        before_send()
        with httpx.Client(verify=True, trust_env=False, follow_redirects=False) as client:
            catalog = discover(
                client,
                cfg,
                config["url"],
                config["protocol"],
                secret,
                configured_profile=True,
                before_connect=credential_boundary,
            )
        if tool == "mcp.catalog":
            return {
                "tools": [
                    {**t, "schema_sha256": schema_digest(t["input_schema"])}
                    for t in catalog["tools"]
                ]
            }
        entry = next((t for t in catalog["tools"] if t["name"] == args["name"]), None)
        if not entry or schema_digest(entry["input_schema"]) != args["schema_sha256"]:
            raise ValueError("MCP schema changed")
        validate(entry["input_schema"], args["arguments"])
        before_send()
        with httpx.Client(verify=True, trust_env=False, follow_redirects=False) as client:
            acknowledgment = discover(
                client,
                cfg,
                config["url"],
                config["protocol"],
                secret,
                configured_profile=True,
                granted_tool=args["name"],
                expected_schema=args["schema_sha256"],
                granted_arguments=args["arguments"],
                before_call=before_send,
                argument_validator=validate,
                before_connect=credential_boundary,
            )
        return {"response": acknowledgment, "effect_verified": False}
    raise ValueError("Tool unavailable")
