"""Fixed, read-only HA assessment. No task, model or document data is transmitted."""

import ipaddress
import json
import re
import time
from typing import Any

import httpx
from fastapi import HTTPException

from hub.config import Settings, read_secret

ORIGIN = "https://home.schlueterbusch.de"
MAX_BYTES = 8_000_000


def text(value: Any, limit: int = 160) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("Unexpected HA text")
    return value


def assessment(client: httpx.Client, token: str, *, allowed_ip: str = "") -> dict[str, Any]:
    base = ORIGIN
    extensions: dict[str, str] = {}
    headers = {"Authorization": "Bearer " + token}
    if allowed_ip:
        ip = ipaddress.ip_address(allowed_ip)
        if not ip.is_global or ip.version != 4:
            raise ValueError("Unreviewed HA address")
        base = "https://" + str(ip)
        headers["Host"] = "home.schlueterbusch.de"
        extensions = {"sni_hostname": "home.schlueterbusch.de"}
    deadline = time.monotonic() + 18

    def get(path: str) -> Any:
        # Only these reviewed paths exist. No redirects, URL parameters or request body.
        with client.stream("GET", base + path, headers=headers, extensions=extensions) as r:
            if r.status_code in (401, 403):
                raise HTTPException(502, "Home-Assistant-Zugang abgewiesen")
            if r.status_code != 200:
                raise HTTPException(502, "Home Assistant liefert keinen gültigen Lesestatus")
            payload = bytearray()
            for chunk in r.iter_bytes(chunk_size=65536):
                payload.extend(chunk)
                if len(payload) > MAX_BYTES or time.monotonic() > deadline:
                    raise ValueError("HA response exceeds limit")
            return json.loads(payload)

    config, states = get("/api/config"), get("/api/states")
    if not isinstance(config, dict) or not isinstance(states, list) or len(states) > 100_000:
        raise ValueError("Unexpected HA schema")
    components = config.get("components")
    if not isinstance(components, list) or not all(isinstance(c, str) for c in components):
        raise ValueError("Unexpected HA components")
    updates = []
    for state in states:
        if not isinstance(state, dict):
            raise ValueError("Unexpected HA state")
        entity = state.get("entity_id")
        if not isinstance(entity, str) or not entity.startswith("update."):
            continue
        if not re.fullmatch(r"update\.[a-z0-9_]{1,200}", entity):
            raise ValueError("Unexpected update entity")
        attrs = state.get("attributes")
        if not isinstance(attrs, dict) or state.get("state") not in (
            "on",
            "off",
            "unknown",
            "unavailable",
        ):
            raise ValueError("Unexpected update schema")
        updates.append(
            {
                "entity_id": entity,
                "name": text(attrs.get("friendly_name")) or entity,
                "state": state["state"],
                "installed_version": text(attrs.get("installed_version")),
                "latest_version": text(attrs.get("latest_version")),
            }
        )
        if len(updates) > 512:
            raise ValueError("Too many update entities")
    return {
        "label": "LOCAL_ONLY",
        "checked_at": time.time(),
        "version": text(config.get("version")),
        "installation_type": text(config.get("installation_type")),
        "supervisor_present": "hassio" in components,
        "backup_integration_present": "backup" in components,
        "restore_verified": False,
        "writes_enabled": False,
        "updates": sorted(updates, key=lambda row: row["entity_id"]),
        "available_updates": sum(row["state"] == "on" for row in updates),
        "unavailable_updates": sum(row["state"] in ("unknown", "unavailable") for row in updates),
        "scope": "configuration_and_update_inventory_only",
    }


def inspect(cfg: Settings) -> dict[str, Any]:
    if not cfg.ha_token_file or not cfg.ha_allowed_ip:
        raise HTTPException(503, "Lesende Home-Assistant-Verbindung noch nicht eingerichtet")
    try:
        token = read_secret(cfg.ha_token_file)
        with httpx.Client(
            verify=True, trust_env=False, follow_redirects=False, timeout=8
        ) as client:
            return assessment(client, token, allowed_ip=cfg.ha_allowed_ip)
    except HTTPException:
        raise
    except (httpx.HTTPError, OSError, ValueError, RecursionError):
        # Response bodies, addresses and secrets never enter the error or model context.
        raise HTTPException(
            502, "Home-Assistant-Leseprüfung fehlgeschlagen; kein Wartungseingriff"
        ) from None
