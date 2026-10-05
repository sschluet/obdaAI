"""Fixed HA installation/backup metadata reads, never backup creation or restore."""

import ipaddress
import json
import logging
import re
import socket
import ssl
import time
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect

from hub.config import Settings, read_secret
from hub.home_assistant import text

COMMANDS = (
    {"type": "supervisor/api", "endpoint": "/info", "method": "get"},
    {"type": "supervisor/api", "endpoint": "/supervisor/info", "method": "get"},
    {"type": "backup/info"},
)
# WebSocket debug frame logging would contain the auth token; disable this private logger.
LOGGER = logging.Logger("hub.ha_backup_transport")
LOGGER.disabled = True


def date(value: Any) -> float | None:
    value = text(value, 64)
    if value is None:
        return None
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("HA backup time must include timezone")
    return result.timestamp()


def flag(value: Any) -> bool | None:
    if value is not None and type(value) is not bool:
        raise ValueError("Unexpected HA backup boolean")
    return value


def summarize(
    info: dict[str, Any], supervisor: dict[str, Any], backups: dict[str, Any]
) -> dict[str, Any]:
    rows, errors = backups.get("backups"), backups.get("agent_errors")
    if not isinstance(rows, list) or len(rows) > 1024 or not isinstance(errors, dict):
        raise ValueError("Unexpected HA backup inventory")
    summary = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Unexpected HA backup entry")
        identity = row.get("backup_id")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", identity):
            raise ValueError("Unexpected HA backup identity")
        agents = row.get("agents")
        if not isinstance(agents, dict) or len(agents) > 32:
            raise ValueError("Unexpected HA backup locations")
        copies = []
        for agent in agents.values():
            if (
                not isinstance(agent, dict)
                or type(agent.get("size")) is not int
                or agent["size"] < 0
            ):
                raise ValueError("Unexpected HA backup size")
            copies.append({"protected": flag(agent.get("protected")), "size": agent["size"]})
        failure_count = 0
        for key in ("failed_addons", "failed_agent_ids", "failed_folders"):
            failures = row.get(key)
            if not isinstance(failures, list):
                raise ValueError("Unexpected HA backup errors")
            failure_count += len(failures)
        summary.append(
            {
                "id": identity,
                "created": date(row.get("date")),
                "homeassistant_included": flag(row.get("homeassistant_included")),
                "database_included": flag(row.get("database_included")),
                "homeassistant_version": text(row.get("homeassistant_version")),
                "copies": copies,
                "failure_count": failure_count,
            }
        )
    if len({row["id"] for row in summary}) != len(summary):
        raise ValueError("Duplicate HA backup identity")
    return {
        "label": "LOCAL_ONLY",
        "checked_at": time.time(),
        "operating_system": text(info.get("operating_system")),
        "core_version": text(info.get("homeassistant")),
        "supervisor_version": text(supervisor.get("version")),
        "supervisor_healthy": flag(supervisor.get("healthy")),
        "supervisor_supported": flag(supervisor.get("supported")),
        "backup_state": text(backups.get("state"), 40),
        "last_completed_automatic_backup": date(backups.get("last_completed_automatic_backup")),
        "agent_error_count": len(errors),
        "backups": sorted(summary, key=lambda row: row["created"] or 0, reverse=True),
        "backup_count": len(summary),
        "restore_verified": False,
        "archive_integrity_verified": False,
        "recovery_key_verified": False,
        "writes_enabled": False,
        "scope": "installation_and_backup_metadata_only",
    }


def exchange(ws: ClientConnection, token: str) -> dict[str, Any]:
    deadline = time.monotonic() + 24

    def receive() -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("HA backup deadline")
        raw = ws.recv(timeout=min(8, remaining))
        if not isinstance(raw, str) or len(raw.encode()) > 1_000_000:
            raise ValueError("Unexpected HA backup framing")
        message = json.loads(raw)
        if not isinstance(message, dict):
            raise ValueError("Unexpected HA backup message")
        return message

    if receive().get("type") != "auth_required":
        raise ValueError("Unexpected HA authentication handshake")
    ws.send(json.dumps({"type": "auth", "access_token": token}))
    if receive().get("type") != "auth_ok":
        raise ValueError("HA backup authentication rejected")
    results = []
    for i, command in enumerate(COMMANDS, 1):
        ws.send(json.dumps({"id": i, **command}))
        message = receive()
        if (
            message.get("type") != "result"
            or type(message.get("id")) is not int
            or message["id"] != i
            or message.get("success") is not True
            or not isinstance(message.get("result"), dict)
        ):
            raise ValueError("HA backup read rejected")
        results.append(message["result"])
    return summarize(*results)


def inspect(cfg: Settings) -> dict[str, Any]:
    if not cfg.ha_token_file or not cfg.ha_allowed_ip:
        raise HTTPException(503, "Lesende Home-Assistant-Verbindung noch nicht eingerichtet")
    try:
        ip = ipaddress.ip_address(cfg.ha_allowed_ip)
        if ip.version != 4 or not ip.is_global:
            raise ValueError("Unreviewed HA backup address")
        token = read_secret(cfg.ha_token_file)
        with socket.create_connection((str(ip), 443), timeout=8) as sock:
            with connect(
                "wss://home.schlueterbusch.de/api/websocket",
                sock=sock,
                ssl=ssl.create_default_context(),
                proxy=None,
                compression=None,
                open_timeout=8,
                close_timeout=2,
                ping_interval=None,
                max_size=1_000_000,
                max_queue=2,
                logger=LOGGER,
                legacy=True,
            ) as ws:
                return exchange(ws, token)
    except (WebSocketException, OSError, ValueError, RecursionError, TimeoutError):
        raise HTTPException(
            502, "HA-Backup-Leseprüfung fehlgeschlagen; kein Wartungseingriff"
        ) from None
