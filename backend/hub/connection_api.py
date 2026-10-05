"""Human-managed MCP connection drafts and bounded catalog checks; no remote grants."""

import json
from typing import Any, Literal

import httpx
from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput, digest, encode
from hub.config import Settings
from hub.db import ToolConnection, ToolConnectionCheck, ToolConnectionRevision, new_id
from hub.knowledge_api import Auth
from hub.mcp_client import VERSIONS, discover, endpoint
from hub.provider_settings import decrypt, encrypt


class ConnectionInput(StrictInput):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=400)
    protocol: Literal["2026-07-28", "2025-11-25", "2025-06-18"] = "2026-07-28"
    auth: Literal["none", "bearer"] = "none"
    token: str | None = Field(default=None, min_length=1, max_length=4096, repr=False)
    clear_secret: bool = False
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_auth(self) -> "ConnectionInput":
        if self.token and (self.auth != "bearer" or self.clear_secret):
            raise ValueError("Conflicting MCP secret operation")
        endpoint(self.url)
        return self


class RevisionInput(StrictInput):
    expected_revision: int = Field(ge=1)


class ArchiveInput(RevisionInput):
    archived: bool


def install_connection_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    def public(db: Session, row: ToolConnection) -> dict[str, Any]:
        data = json.loads(row.config)
        checked = db.scalar(
            select(ToolConnectionCheck)
            .where(ToolConnectionCheck.connection_id == row.id)
            .order_by(ToolConnectionCheck.created.desc())
        )
        allowed = json.loads(cfg.mcp_endpoints_json)
        return {
            "id": row.id,
            "name": row.name,
            "revision": row.revision,
            "archived": row.archived,
            "config": data,
            "secret_saved": bool(row.encrypted_secret),
            "target_approved": data["url"] in allowed,
            "last_check": {
                "revision": checked.revision,
                "created": checked.created,
                "result": json.loads(checked.result),
            }
            if checked
            else None,
        }

    @app.get("/api/connections")
    def listing(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return {
                "connections": [
                    public(db, r)
                    for r in db.scalars(select(ToolConnection).order_by(ToolConnection.created))
                ],
                "protocols": list(VERSIONS),
                "encrypted_secrets_available": bool(cfg.secrets_key_file),
                "supported_transport": "streamable_http",
                "remote_execution_available": False,
            }

    def lock_mutation(db: Session) -> None:
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))

    def save(body: ConnectionInput, connection_id: str | None) -> dict[str, Any]:
        with factory() as db:
            lock_mutation(db)
            if connection_id:
                row = db.scalar(
                    select(ToolConnection)
                    .where(ToolConnection.id == connection_id)
                    .with_for_update()
                )
                if not row:
                    raise HTTPException(404, "Verbindung nicht gefunden")
                if row.revision != body.expected_revision or row.archived:
                    raise HTTPException(409, "Verbindung geändert oder archiviert; neu laden")
                previous = json.loads(row.config)
                # Never forward the old credential to a different target or auth scheme.
                if (
                    previous["url"] != body.url or previous["auth"] != body.auth
                ) and not body.token:
                    row.encrypted_secret = None
                row.revision += 1
            else:
                if body.expected_revision is not None:
                    raise HTTPException(422, "Neue Verbindung besitzt noch keine Revision")
                row = ToolConnection(
                    id=new_id(), revision=1, name=body.name, config="{}", archived=False
                )
                db.add(row)
            if body.token:
                try:
                    row.encrypted_secret = encrypt(cfg, "mcp:" + row.id, body.token)
                except (ValueError, OSError):
                    raise HTTPException(503, "Serververschlüsselung nicht verfügbar") from None
            if body.clear_secret or body.auth == "none":
                row.encrypted_secret = None
            row.name = body.name
            row.config = encode(
                body.model_dump(exclude={"token", "clear_secret", "expected_revision"})
            )
            db.flush()
            db.add(
                ToolConnectionRevision(
                    connection_id=row.id, revision=row.revision, config=row.config
                )
            )
            db.commit()
            return public(db, row)

    @app.post("/api/connections")
    def create(body: ConnectionInput, auth: Auth) -> dict[str, Any]:
        return save(body, None)

    @app.put("/api/connections/{connection_id}")
    def edit(connection_id: str, body: ConnectionInput, auth: Auth) -> dict[str, Any]:
        return save(body, connection_id)

    @app.patch("/api/connections/{connection_id}/control")
    def archive(connection_id: str, body: ArchiveInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock_mutation(db)
            row = db.scalar(
                select(ToolConnection)
                .where(ToolConnection.id == connection_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not row:
                raise HTTPException(404, "Verbindung nicht gefunden")
            if row.revision != body.expected_revision:
                raise HTTPException(409, "Verbindung geändert; neu laden")
            row.archived = body.archived
            row.revision += 1
            db.add(
                ToolConnectionRevision(
                    connection_id=row.id,
                    revision=row.revision,
                    config=encode({**json.loads(row.config), "archived": row.archived}),
                )
            )
            db.commit()
            return public(db, row)

    @app.get("/api/connections/{connection_id}/revisions")
    def history(connection_id: str, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            return [
                {"revision": r.revision, "config": json.loads(r.config), "created": r.created}
                for r in db.scalars(
                    select(ToolConnectionRevision)
                    .where(ToolConnectionRevision.connection_id == connection_id)
                    .order_by(ToolConnectionRevision.revision.desc())
                )
            ]

    @app.post("/api/connections/{connection_id}/check")
    def check(connection_id: str, body: RevisionInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            row = db.get(ToolConnection, connection_id)
            if not row:
                raise HTTPException(404, "Verbindung nicht gefunden")
            if row.archived or row.revision != body.expected_revision:
                raise HTTPException(409, "Verbindung geändert oder archiviert")
            revision, config = row.revision, json.loads(row.config)
            try:
                token = (
                    decrypt(cfg, "mcp:" + row.id, row.encrypted_secret)
                    if row.encrypted_secret
                    else ""
                )
                if config["auth"] == "bearer" and not token:
                    raise ValueError("Missing MCP credential")
                with httpx.Client(
                    verify=True, trust_env=False, follow_redirects=False, timeout=8
                ) as client:
                    report = discover(client, cfg, config["url"], config["protocol"], token)
                report["catalog_sha256"] = digest(encode(report["tools"]))
                report["status"] = "succeeded"
            except (httpx.HTTPError, ValueError, OSError, TypeError, RecursionError, InvalidTag):
                report = {
                    "status": "failed",
                    "label": "LOCAL_ONLY",
                    "execution_allowed": False,
                    "message": "Verbindung, Authentifizierung, Protokoll oder Zielfreigabe prüfen",
                }
            actual = db.scalar(
                select(ToolConnection)
                .where(ToolConnection.id == connection_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not actual or actual.archived or actual.revision != revision:
                raise HTTPException(409, "Verbindung während Prüfung geändert; Ergebnis verworfen")
            db.add(
                ToolConnectionCheck(
                    connection_id=connection_id, revision=revision, result=encode(report)
                )
            )
            db.commit()
            return public(db, actual)
