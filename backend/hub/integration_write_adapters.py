"""Fixed reversible integration operations. All arguments remain inert local data.

No shell/exec, arbitrary HTTP paths, redirects or dynamically imported MCP tools.
The caller owns the grant, persisted dispatch intent and reconciliation boundary.
"""

import base64
import hashlib
import io
import json
import math
import socket
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import httpx
import paramiko  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from hub.config import Settings
from hub.integration_transport import pinned_target, resolved_targets


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HATarget(Arguments):
    entity_id: str = Field(pattern=r"^(light|switch|input_boolean|fan)\.[a-z0-9_]{1,120}$")
    state: Literal["on", "off"]


class HANumber(Arguments):
    entity_id: str = Field(pattern=r"^(input_number|number)\.[a-z0-9_]{1,120}$")
    value: float = Field(allow_inf_nan=False)


class HASelect(Arguments):
    entity_id: str = Field(pattern=r"^(input_select|select)\.[a-z0-9_]{1,120}$")
    option: str = Field(min_length=1, max_length=256)


class PaperlessMetadata(Arguments):
    document_id: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=128)
    tags: list[int] | None = Field(default=None, max_length=100)
    correspondent: int | None = Field(default=None, ge=1)
    document_type: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def nonempty(self) -> "PaperlessMetadata":
        if not (self.model_fields_set - {"document_id"}):
            raise ValueError("At least one metadata field required")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("Title cannot be null")
        if "tags" in self.model_fields_set and (
            self.tags is None or any(type(i) is not int or i < 1 for i in self.tags)
        ):
            raise ValueError("Invalid tags")
        if self.tags is not None:
            self.tags = sorted(set(self.tags))
        return self


class SSHText(Arguments):
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.txt$")
    content: str = Field(max_length=100_000)


class UniFiGuest(Arguments):
    site_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    client_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    authorized: bool
    time_limit_minutes: int = Field(default=60, ge=1, le=1440)

    @model_validator(mode="after")
    def ids(self) -> "UniFiGuest":
        UUID(self.site_id)
        UUID(self.client_id)
        return self


class MCPCall(Arguments):
    tool_name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    arguments: dict[str, Any]


MODELS: dict[str, dict[str, tuple[str, type[Arguments]]]] = {
    "home_assistant": {
        "entity.set_power": ("Gerät ein-/ausschalten", HATarget),
        "entity.set_number": ("Zahlenwert setzen", HANumber),
        "entity.select_option": ("Option auswählen", HASelect),
    },
    "paperless": {"document.update_metadata": ("Dokumentdaten ändern", PaperlessMetadata)},
    "ssh": {"file.write_text": ("Textdatei im obdaAI-Ordner schreiben", SSHText)},
    "unifi": {"guest.set_access": ("Gastzugang zeitlich freigeben oder entziehen", UniFiGuest)},
    "mcp": {"tool.call": ("Einzelnes MCP-Werkzeug nach Schemaprüfung aufrufen", MCPCall)},
}


def capabilities(kind: str) -> list[dict[str, Any]]:
    return [
        {"id": key, "name": name, "parameters_schema": model.model_json_schema()}
        for key, (name, model) in MODELS.get(kind, {}).items()
    ]


def validate_arguments(kind: str, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    pair = MODELS.get(kind, {}).get(operation)
    if not pair:
        raise ValueError("Operation not implemented")
    return pair[1].model_validate(arguments).model_dump(exclude_unset=kind == "paperless")


def validate_mcp_value(schema: dict[str, Any], value: Any, depth: int = 0) -> None:
    """Deliberately bounded schema subset, without refs, regex or executable extensions."""
    if depth > 8 or len(json.dumps(schema)) > 32000:
        raise ValueError("MCP schema limit")
    if set(schema) - {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "title",
        "description",
        "default",
    }:
        raise ValueError("MCP schema feature not supported")
    kind = schema.get("type")
    types: dict[str, Any] = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
        "integer": int,
        "number": (int, float),
        "null": type(None),
    }
    if kind not in types or not isinstance(value, types[kind]):
        raise ValueError("MCP argument type mismatch")
    if kind in {"number", "integer"} and (isinstance(value, bool) or not math.isfinite(value)):
        raise ValueError("MCP number invalid")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("MCP enum mismatch")
    if kind == "object":
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is not False or set(value) - set(props):
            raise ValueError("MCP requires closed reviewed object schemas")
        if set(schema.get("required", [])) - set(value) or len(value) > 100:
            raise ValueError("MCP required argument missing")
        for key, item in value.items():
            validate_mcp_value(props[key], item, depth + 1)
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= min(schema.get("maxItems", 100), 100):
            raise ValueError("MCP array limit")
        for item in value:
            validate_mcp_value(schema.get("items", {}), item, depth + 1)
    elif kind == "string":
        if (
            not schema.get("minLength", 0)
            <= len(value)
            <= min(schema.get("maxLength", 10000), 10000)
        ):
            raise ValueError("MCP string limit")
    elif kind in {"number", "integer"}:
        if not schema.get("minimum", float("-inf")) <= value <= schema.get("maximum", float("inf")):
            raise ValueError("MCP number bound")


def mcp_catalog(cfg: Settings, config: dict[str, Any], secret: str) -> dict[str, Any]:
    from hub.mcp_client import discover

    with httpx.Client(verify=True, trust_env=False, follow_redirects=False) as client:
        return discover(
            client, cfg, config["url"], config["protocol"], secret, configured_profile=True
        )


def request(
    cfg: Settings,
    config: dict[str, Any],
    secret: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    before_send: Callable[[], Any] | None = None,
) -> Any:
    base = config["url"].rstrip("/")
    if config["kind"] == "paperless" and base.endswith("/api"):
        base = base[:-4]
    pinned, headers, extensions = pinned_target(cfg, base)
    if not secret or len(secret) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in secret):
        raise ValueError("Invalid integration credential")
    headers.update(
        {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
    )
    if config["kind"] == "unifi":
        headers["X-API-KEY"] = secret
    else:
        headers["Authorization"] = (
            "Token " if config["kind"] == "paperless" else "Bearer "
        ) + secret
    with httpx.Client(verify=True, trust_env=False, follow_redirects=False) as client:
        deadline = time.monotonic() + 25
        if method != "GET" and before_send:
            before_send()
        with client.stream(
            method,
            pinned.rstrip("/") + path,
            json=body,
            headers=headers,
            extensions=extensions,
            timeout=15,
        ) as response:
            if response.status_code not in (200, 201, 204):
                raise ValueError("Integration HTTP failure")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("Compressed response unsupported")
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > 1_000_000 or time.monotonic() > deadline:
                    raise ValueError("Integration response limit")
            return json.loads(data) if data else {}


@contextmanager
def ssh_client(
    cfg: Settings,
    config: dict[str, Any],
    secret: str,
    before_auth: Callable[[str], Any] | None = None,
) -> Iterator[Any]:
    addresses = resolved_targets(cfg, config["url"], ssh_port=config["port"])
    address, port = addresses[0]
    key_type, key_data = config["host_key"].split()[:2]
    pinned_key = paramiko.PKey.from_type_string(key_type, base64.b64decode(key_data, validate=True))
    client = paramiko.SSHClient()
    host_alias = config["url"] if port == 22 else f"[{config['url']}]:{port}"
    client.get_host_keys().add(host_alias, key_type, pinned_key)
    sock = socket.create_connection((address, port), timeout=8)
    try:
        if before_auth:
            authenticate = client._auth

            def checked_auth(*args: Any, **kwargs: Any) -> Any:
                before_auth(address)
                return authenticate(*args, **kwargs)

            client._auth = checked_auth
        opts: dict[str, Any] = {"password": secret} if config["auth"] == "password" else {}
        if config["auth"] == "private_key":
            key = None
            for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
                try:
                    key = cls.from_private_key(io.StringIO(secret))
                    break
                except (paramiko.SSHException, ValueError):
                    continue
            if key is None:
                raise ValueError("Unsupported or encrypted SSH key")
            if config.get("certificate"):
                key.load_certificate(config["certificate"])
            opts["pkey"] = key
        client.connect(
            config["url"],
            port=port,
            username=config["username"],
            sock=sock,
            allow_agent=False,
            look_for_keys=False,
            timeout=8,
            banner_timeout=8,
            auth_timeout=8,
            channel_timeout=10,
            **opts,
        )
        yield client
    finally:
        client.close()
        sock.close()


@contextmanager
def sftp(
    cfg: Settings,
    config: dict[str, Any],
    secret: str,
    before_auth: Callable[[str], Any] | None = None,
) -> Iterator[Any]:
    with ssh_client(cfg, config, secret, before_auth) as client:
        with client.open_sftp() as remote:
            remote.get_channel().settimeout(10)
            yield remote


def ssh_state(remote: Any, filename: str) -> dict[str, Any]:
    root = remote.normalize(".") + "/obdaai-managed"
    try:
        folder = remote.lstat(root)
        if not stat.S_ISDIR(folder.st_mode):
            raise ValueError("Managed folder must be a real directory")
    except FileNotFoundError:
        return {"exists": False, "sha256": None}
    path = root + "/" + filename
    try:
        current = remote.lstat(path)
    except FileNotFoundError:
        return {"exists": False, "sha256": None}
    if not stat.S_ISREG(current.st_mode) or current.st_size > 400_000:
        raise ValueError("Managed target must be a bounded regular file")
    with remote.open(path, "rb") as source:
        data = source.read(400_001)
    if len(data) > 400_000:
        raise ValueError("SSH file exceeds limit")
    return {"exists": True, "sha256": hashlib.sha256(data).hexdigest()}


def snapshot(
    cfg: Settings,
    config: dict[str, Any],
    secret: str,
    operation: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    if config["kind"] == "mcp":
        from hub.mcp_client import schema_digest

        catalog = mcp_catalog(cfg, config, secret)
        tool = next((t for t in catalog["tools"] if t["name"] == args["tool_name"]), None)
        if not tool or schema_digest(tool["input_schema"]) != args["schema_sha256"]:
            raise ValueError("MCP tool schema changed")
        validate_mcp_value(tool["input_schema"], args["arguments"])
        return {
            "tool_name": args["tool_name"],
            "schema": tool["input_schema"],
            "schema_sha256": args["schema_sha256"],
            "remote_state_readable": False,
        }
    if config["kind"] == "unifi":
        row = request(
            cfg, config, secret, "GET", f"/v1/sites/{args['site_id']}/clients/{args['client_id']}"
        )
        if row.get("id") != args["client_id"] or row.get("access", {}).get("type") != "GUEST":
            raise ValueError("Selected client is not a guest")
        access = row["access"]
        authorization = access.get("authorization") or {}
        return {
            "id": row["id"],
            "access": {
                "type": access["type"],
                "authorized": access.get("authorized"),
                "authorization": {
                    k: authorization.get(k)
                    for k in (
                        "authorizationMethod",
                        "authorizedAt",
                        "expiresAt",
                        "dataUsageLimitMBytes",
                        "rxRateLimitKbps",
                        "txRateLimitKbps",
                    )
                },
            },
        }
    if config["kind"] == "ssh":
        with sftp(cfg, config, secret) as remote:
            return ssh_state(remote, args["filename"])
    if config["kind"] == "paperless":
        from hub.paperless_client import metadata

        row = request(cfg, config, secret, "GET", f"/api/documents/{args['document_id']}/")
        row = metadata(row)
        row["tags"] = sorted(row["tags"])
        if row.get("id") != args["document_id"]:
            raise ValueError("Document identity changed")
        return {
            k: row.get(k)
            for k in ("id", "modified", "title", "tags", "correspondent", "document_type")
        }
    row = request(cfg, config, secret, "GET", "/api/states/" + args["entity_id"])
    if row.get("entity_id") != args["entity_id"]:
        raise ValueError("Entity identity changed")
    attributes = row.get("attributes", {})
    if operation == "entity.set_number":
        if (
            not attributes.get("min", float("-inf"))
            <= args["value"]
            <= attributes.get("max", float("inf"))
        ):
            raise ValueError("Number outside entity range")
    if operation == "entity.select_option" and args["option"] not in attributes.get("options", []):
        raise ValueError("Option unavailable")
    return {
        "entity_id": row["entity_id"],
        "state": row["state"],
        "last_updated": row.get("last_updated"),
    }


def matches(kind: str, operation: str, args: dict[str, Any], state: dict[str, Any]) -> bool:
    if kind == "mcp":
        return False  # Catalog equality cannot reconcile an unknown remote effect.
    if kind == "unifi":
        access = state.get("access", {})
        if access.get("authorized") is not args["authorized"]:
            return False
        if not args["authorized"]:
            return True
        authorization = access.get("authorization", {})
        try:
            start = datetime.fromisoformat(authorization["authorizedAt"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(authorization["expiresAt"].replace("Z", "+00:00"))
            return bool(
                start.tzinfo
                and end.tzinfo
                and abs((end - start).total_seconds() - args["time_limit_minutes"] * 60) <= 1
            )
        except (KeyError, ValueError, TypeError, AttributeError):
            return False
    if kind == "ssh":
        return (
            state.get("exists") is True
            and state.get("sha256") == hashlib.sha256(args["content"].encode()).hexdigest()
        )
    if kind == "paperless":
        return all(state.get(k) == v for k, v in args.items() if k != "document_id")
    if operation == "entity.set_number":
        try:
            return bool(float(state["state"]) == args["value"])
        except (ValueError, KeyError):
            return False
    return bool(state.get("state") == args.get("state", args.get("option")))


def apply(
    cfg: Settings,
    config: dict[str, Any],
    secret: str,
    operation: str,
    args: dict[str, Any],
    request_id: str,
    before_send: Callable[[], Any] | None = None,
) -> dict[str, Any] | None:
    if config["kind"] == "mcp":
        from hub.mcp_client import discover

        with httpx.Client(verify=True, trust_env=False, follow_redirects=False) as client:
            return discover(
                client,
                cfg,
                config["url"],
                config["protocol"],
                secret,
                configured_profile=True,
                granted_tool=args["tool_name"],
                expected_schema=args["schema_sha256"],
                granted_arguments=args["arguments"],
                before_call=before_send,
            )
    if config["kind"] == "unifi":
        payload: dict[str, Any] = {
            "action": "AUTHORIZE_GUEST_ACCESS" if args["authorized"] else "UNAUTHORIZE_GUEST_ACCESS"
        }
        if args["authorized"]:
            payload["timeLimitMinutes"] = args["time_limit_minutes"]
        request(
            cfg,
            config,
            secret,
            "POST",
            f"/v1/sites/{args['site_id']}/clients/{args['client_id']}/actions",
            payload,
            before_send,
        )
        return None
    if config["kind"] == "ssh":
        with sftp(cfg, config, secret) as remote:
            root = remote.normalize(".") + "/obdaai-managed"
            if before_send:
                before_send()
            try:
                remote.mkdir(root, mode=0o700)
            except OSError:
                if not stat.S_ISDIR(remote.lstat(root).st_mode):
                    raise ValueError("Unsafe SSH folder") from None
            previous = ssh_state(remote, args["filename"])
            if previous["exists"]:
                with remote.open(root + "/" + args["filename"], "rb") as source:
                    original = source.read(400_001)
                if len(original) > 400_000:
                    raise ValueError("SSH original exceeds bound")
                backup = root + "/.obdaai-before-" + request_id
                with remote.open(backup, "wx") as output:
                    output.write(original)
                remote.chmod(backup, 0o600)
            temp = root + "/.obdaai-" + request_id
            with remote.open(temp, "wx") as output:
                output.write(args["content"].encode())
                output.flush()
            remote.chmod(temp, 0o600)
            remote.posix_rename(temp, root + "/" + args["filename"])
        return None
    if config["kind"] == "paperless":
        request(
            cfg,
            config,
            secret,
            "PATCH",
            f"/api/documents/{args['document_id']}/",
            {k: v for k, v in args.items() if k != "document_id"},
            before_send,
        )
        return None
    domain = args["entity_id"].split(".")[0]
    service, data = (
        ("turn_" + args["state"], {})
        if operation == "entity.set_power"
        else ("set_value", {"value": args["value"]})
        if operation == "entity.set_number"
        else ("select_option", {"option": args["option"]})
    )
    request(
        cfg,
        config,
        secret,
        "POST",
        f"/api/services/{domain}/{service}",
        {"entity_id": args["entity_id"], **data},
        before_send,
    )
    return None


def check_connection(cfg: Settings, config: dict[str, Any], secret: str) -> dict[str, Any]:
    try:
        if config["kind"] == "ssh":
            with sftp(cfg, config, secret) as remote:
                remote.normalize(".")
        elif config["kind"] == "unifi":
            request(cfg, config, secret, "GET", "/v1/info")
        else:
            raise ValueError("Unsupported check")
        return {"label": "LOCAL_ONLY", "authenticated": True, "write_performed": False}
    except (paramiko.SSHException, OSError) as exc:
        raise ValueError("Integration check failed") from exc
