"""Operator-whitelisted empty-input MCP reads. Catalog annotations grant no rights."""

import json
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from hub.config import Settings
from hub.db import ToolConnection, ToolConnectionCheck
from hub.mcp_client import discover, schema_digest, target
from hub.provider_settings import decrypt


def validate_connection(db: Session, cfg: Settings, params: dict[str, Any]) -> ToolConnection:
    row = db.scalar(
        select(ToolConnection)
        .where(ToolConnection.id == params["connection_id"])
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row or row.archived or row.revision != params["expected_revision"]:
        raise HTTPException(409, "MCP-Verbindung geändert, archiviert oder nicht vorhanden")
    config = json.loads(row.config)
    rules = json.loads(cfg.mcp_read_tools_json)
    try:
        target(cfg, config["url"])
        if (
            not isinstance(rules, dict)
            or not isinstance(rules.get(config["url"]), dict)
            or rules[config["url"]].get(params["tool_name"]) != params["schema_sha256"]
        ):
            raise ValueError("Unapproved MCP read")
    except (ValueError, KeyError):
        raise HTTPException(403, "MCP-Lesewerkzeug nicht serverseitig freigegeben") from None
    checked = db.scalar(
        select(ToolConnectionCheck)
        .where(
            ToolConnectionCheck.connection_id == row.id,
            ToolConnectionCheck.revision == row.revision,
        )
        .order_by(ToolConnectionCheck.created.desc())
        .limit(1)
    )
    tools = json.loads(checked.result).get("tools", []) if checked else []
    if not any(
        t["name"] == params["tool_name"]
        and schema_digest(t["input_schema"]) == params["schema_sha256"]
        for t in tools
    ):
        raise HTTPException(409, "Aktuellen Werkzeugkatalog zuerst prüfen")
    return row


def read_connection(db: Session, cfg: Settings, params: dict[str, Any]) -> dict[str, Any]:
    row = validate_connection(db, cfg, params)
    config = json.loads(row.config)
    try:
        if config["auth"] == "bearer" and not row.encrypted_secret:
            raise ValueError("Missing MCP secret")
        token = (
            decrypt(cfg, "mcp:" + row.id, row.encrypted_secret or "")
            if config["auth"] == "bearer"
            else ""
        )
        if config["auth"] == "bearer" and not token:
            raise ValueError("Missing MCP secret")
        with httpx.Client(
            verify=True, trust_env=False, follow_redirects=False, timeout=8
        ) as client:
            result = discover(
                client,
                cfg,
                config["url"],
                config["protocol"],
                token,
                read_tool=params["tool_name"],
                expected_schema=params["schema_sha256"],
            )
        return {**result, "connection_id": row.id, "connection_revision": row.revision}
    except (httpx.HTTPError, ValueError, OSError, InvalidTag, RecursionError):
        raise HTTPException(
            502, "MCP-Leseaufruf gestoppt; keine automatische Wiederholung"
        ) from None
