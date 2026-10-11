"""Human-managed generic integration registry; saving never grants network access."""

import json
import re
import time
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput, encode
from hub.config import Settings
from hub.db import Conversation, Project, Run, Task, TaskRun
from hub.db_locks import ownership_lock
from hub.home_assistant import ORIGIN, assessment
from hub.integrations import Integration, IntegrationBinding
from hub.knowledge_api import Auth
from hub.mcp_client import discover, endpoint, target
from hub.provider_settings import decrypt, encrypt

IntegrationKind = Literal["home_assistant", "paperless", "mcp", "unifi", "ssh"]
Scope = Literal["project", "task", "conversation"]
TYPES = ["home_assistant", "paperless", "mcp", "unifi", "ssh"]


class IntegrationInput(StrictInput):
    name: str = Field(min_length=1, max_length=80)
    kind: IntegrationKind
    url: str = Field(min_length=1, max_length=400)
    auth: Literal["api_key", "none", "bearer", "password", "private_key"]
    username: str = Field(default="", max_length=128)
    port: int = Field(default=22, ge=1, le=65535)
    host_key: str = Field(default="", max_length=4096)
    protocol: Literal["2026-07-28", "2025-11-25", "2025-06-18"] = "2026-07-28"
    certificate: str = Field(default="", max_length=16384)
    secret: str | None = Field(default=None, min_length=1, max_length=32768, repr=False)
    clear_secret: bool = False
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_target(self) -> "IntegrationInput":
        if not self.name.strip() or self.secret and (self.clear_secret or self.auth == "none"):
            raise ValueError("Conflicting credential operation or empty name")
        if any(ord(c) < 32 for c in self.url + self.username):
            raise ValueError("Invalid target")
        schemes = {
            "home_assistant": {"api_key", "bearer"},
            "paperless": {"api_key"},
            "unifi": {"api_key"},
            "mcp": {"none", "bearer"},
            "ssh": {"password", "private_key"},
        }
        if self.auth not in schemes[self.kind]:
            raise ValueError("Authentication does not match integration type")
        if self.kind == "ssh":
            # Host only; no URI credentials, command, path, query or ssh options.
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", self.url):
                raise ValueError("SSH requires a host name or IP address")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}", self.username):
                raise ValueError("SSH requires a user name")
            if not re.fullmatch(
                r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) "
                r"[A-Za-z0-9+/]+={0,3}(?: [^\r\n]+)?",
                self.host_key,
            ):
                raise ValueError("SSH requires a pinned public host key")
            if self.certificate and (
                self.auth != "private_key"
                or not re.fullmatch(
                    r"[A-Za-z0-9-]+-cert-v01@openssh.com [A-Za-z0-9+/]+={0,3}(?: [^\r\n]+)?",
                    self.certificate,
                )
            ):
                raise ValueError("Invalid public SSH user certificate")
        else:
            u = urlsplit(self.url)
            if (
                u.scheme != "https"
                or not u.hostname
                or u.username
                or u.password
                or u.query
                or u.fragment
                or "\\" in self.url
                or "%" in self.url
                or any(ord(c) > 126 or ord(c) < 33 for c in self.url)
            ):
                # Existing MCP loopback fixtures stay supported by its bounded adapter.
                if self.kind != "mcp":
                    raise ValueError("Integration requires a plain HTTPS endpoint")
            if self.kind == "mcp":
                endpoint(self.url)
            else:
                _ = u.port
            if self.username or self.host_key or self.certificate:
                raise ValueError("SSH fields require an SSH connection")
        if self.secret and self.auth in {"api_key", "bearer"}:
            if len(self.secret) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in self.secret):
                raise ValueError("Invalid API credential")
        return self


class RevisionInput(StrictInput):
    expected_revision: int = Field(ge=1)


class ControlInput(RevisionInput):
    enabled: bool


class BindingInput(StrictInput):
    expected_revision: int = Field(ge=0)
    integration_ids: list[UUID] = Field(default_factory=list, max_length=8)
    selection_mode: Literal["off", "manual", "automatic", "inherit"] = "manual"

    @model_validator(mode="after")
    def unique_ids(self) -> "BindingInput":
        if len(set(self.integration_ids)) != len(self.integration_ids):
            raise ValueError("Duplicate integration selection")
        return self


def approved(cfg: Settings, row: Integration) -> bool:
    config = json.loads(row.config)
    if row.kind == "home_assistant":
        return config["url"] == ORIGIN and bool(cfg.ha_allowed_ip)
    if row.kind == "mcp":
        try:
            target(cfg, config["url"])
            return True
        except (ValueError, TypeError):
            return False
    return False


def integration_info(cfg: Settings, row: Integration) -> dict[str, Any]:
    checked = json.loads(row.last_check) if row.last_check else None
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "revision": row.revision,
        "enabled": row.enabled,
        "config": json.loads(row.config),
        "secret_saved": bool(row.encrypted_secret),
        "target_approved": approved(cfg, row),
        "last_check": checked,
        "execution_available": False,
        "status": (
            "disabled"
            if not row.enabled
            else "checked"
            if checked
            and checked.get("revision") == row.revision
            and checked.get("status") == "succeeded"
            else "configured"
        ),
    }


def binding_owner(db: Session, scope: Scope, owner_id: str) -> None:
    owner: Project | Task | Conversation | None
    if scope == "project":
        owner = db.scalar(select(Project).where(Project.id == owner_id).with_for_update())
    elif scope == "task":
        owner = db.scalar(select(Task).where(Task.id == owner_id).with_for_update())
    else:
        owner = db.scalar(select(Conversation).where(Conversation.id == owner_id).with_for_update())
    if not owner or owner.archived or (isinstance(owner, Conversation) and owner.purpose != "chat"):
        raise HTTPException(404, "Bereich nicht vorhanden oder archiviert")


def binding_info(db: Session, scope: Scope, owner_id: str) -> dict[str, Any]:
    row = db.get(IntegrationBinding, (scope, owner_id))
    ids = json.loads(row.integration_ids) if row else []
    mode = row.selection_mode if row else "inherit" if scope == "conversation" else "manual"
    resolved_ids = ids
    if mode == "inherit":
        conversation = db.get(Conversation, owner_id)
        if conversation and conversation.project_id:
            project = db.get(Project, conversation.project_id)
            if project and not project.archived:
                inherited = binding_info(db, "project", project.id)
                resolved_ids = inherited["effective_integration_ids"]
    effective = [
        item.id
        for item in db.scalars(select(Integration).where(Integration.id.in_(resolved_ids)))
        if item.enabled and mode != "off"
    ]
    return {
        "scope": scope,
        "owner_id": owner_id,
        "revision": row.revision if row else 0,
        "integration_ids": ids,
        "selection_mode": mode,
        "effective_integration_ids": [item for item in resolved_ids if item in effective],
        "execution_available": False,
    }


def freeze_bindings(db: Session, scope: Scope, owner_id: str) -> dict[str, Any]:
    """Metadata only. Selection does not execute tools or expose credentials."""
    selection = binding_info(db, scope, owner_id)
    rows = {
        r.id: r
        for r in db.scalars(
            select(Integration).where(Integration.id.in_(selection["effective_integration_ids"]))
        )
    }
    return {
        "mode": selection["selection_mode"],
        "revision": selection["revision"],
        "bindings": [
            {
                "id": rows[i].id,
                "revision": rows[i].revision,
                "kind": rows[i].kind,
                "name": rows[i].name,
                "enabled": rows[i].enabled,
                "execution_available": False,
            }
            for i in selection["effective_integration_ids"]
        ],
        "execution_available": False,
    }


def install_integration_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    def lock(db: Session) -> None:
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        else:
            # Registry first, before any owner row; deletion must use the same order.
            db.execute(text("SELECT pg_advisory_xact_lock(791103050)"))

    @app.get("/api/integrations")
    def listing(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            rows = list(db.scalars(select(Integration).order_by(Integration.created)))
            counts = {r.id: {"project": 0, "task": 0, "conversation": 0} for r in rows}
            for binding in db.scalars(select(IntegrationBinding)):
                for integration_id in json.loads(binding.integration_ids):
                    if integration_id in counts:
                        counts[integration_id][binding.scope] += 1
            return {
                "integrations": [
                    {**integration_info(cfg, r), "binding_counts": counts[r.id]} for r in rows
                ],
                "types": TYPES,
                "encrypted_secrets_available": bool(cfg.secrets_key_file),
            }

    def save(body: IntegrationInput, integration_id: str | None) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            row = db.get(Integration, integration_id) if integration_id else None
            if integration_id:
                if not row:
                    raise HTTPException(404, "Integration nicht gefunden")
                if row.revision != body.expected_revision:
                    raise HTTPException(409, "Integration geändert; neu laden")
                previous = json.loads(row.config)
                if any(
                    previous.get(k) != getattr(body, k)
                    for k in ("kind", "url", "auth", "username", "port", "host_key", "certificate")
                ):
                    row.encrypted_secret = None
                row.revision += 1
            else:
                if body.expected_revision is not None:
                    raise HTTPException(422, "Neue Integration besitzt keine Revision")
                row = Integration(name=body.name, kind=body.kind, config="{}", enabled=False)
                db.add(row)
                db.flush()
            assert row is not None
            if body.secret:
                try:
                    row.encrypted_secret = encrypt(cfg, "integration:" + row.id, body.secret)
                except (ValueError, OSError):
                    raise HTTPException(503, "Serververschlüsselung nicht verfügbar") from None
            if body.clear_secret or body.auth == "none":
                row.encrypted_secret = None
            row.name, row.kind = body.name.strip(), body.kind
            row.config = encode(
                body.model_dump(exclude={"secret", "clear_secret", "expected_revision", "name"})
            )
            db.commit()
            return integration_info(cfg, row)

    @app.post("/api/integrations")
    def create(body: IntegrationInput, auth: Auth) -> dict[str, Any]:
        return save(body, None)

    @app.put("/api/integrations/{integration_id}")
    def edit(integration_id: UUID, body: IntegrationInput, auth: Auth) -> dict[str, Any]:
        return save(body, str(integration_id))

    @app.delete("/api/integrations/{integration_id}")
    def remove(integration_id: UUID, body: RevisionInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            row = db.get(Integration, str(integration_id))
            if not row:
                raise HTTPException(404, "Integration nicht gefunden")
            if row.revision != body.expected_revision:
                raise HTTPException(409, "Integration geändert; neu laden")
            if any(
                str(integration_id) in json.loads(binding.integration_ids)
                for binding in db.scalars(select(IntegrationBinding))
            ):
                raise HTTPException(
                    409, "Integration zuerst aus Projekten, Aufgaben und Chats lösen"
                )
            db.delete(row)
            db.commit()
            return {"deleted": True, "id": str(integration_id)}

    @app.patch("/api/integrations/{integration_id}/control")
    def control(integration_id: UUID, body: ControlInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            row = db.get(Integration, str(integration_id))
            if not row:
                raise HTTPException(404, "Integration nicht gefunden")
            if row.revision != body.expected_revision:
                raise HTTPException(409, "Integration geändert; neu laden")
            row.enabled = body.enabled
            row.revision += 1
            db.commit()
            return integration_info(cfg, row)

    @app.post("/api/integrations/{integration_id}/check")
    def check(integration_id: UUID, body: RevisionInput, auth: Auth) -> dict[str, Any]:
        # Do not hold owner/global locks during network I/O.
        with factory() as db:
            row = db.get(Integration, str(integration_id))
            if not row:
                raise HTTPException(404, "Integration nicht gefunden")
            if row.revision != body.expected_revision:
                raise HTTPException(409, "Integration geändert; neu laden")
            revision, config = row.revision, json.loads(row.config)
            report: dict[str, Any] = {
                "revision": revision,
                "created": time.time(),
                "label": "LOCAL_ONLY",
                "status": "blocked",
                "message": "Netzwerkziel und Adapter noch nicht freigegeben",
                "execution_allowed": False,
            }
            if approved(cfg, row):
                try:
                    secret = (
                        decrypt(cfg, "integration:" + row.id, row.encrypted_secret)
                        if row.encrypted_secret
                        else ""
                    )
                    if config["auth"] != "none" and not secret:
                        raise ValueError("Missing credential")
                    with httpx.Client(
                        verify=True, trust_env=False, follow_redirects=False, timeout=8
                    ) as client:
                        result = (
                            discover(client, cfg, config["url"], config["protocol"], secret)
                            if row.kind == "mcp"
                            else assessment(client, secret, allowed_ip=cfg.ha_allowed_ip)
                        )
                    report.update(
                        status="succeeded", message="Lesende Verbindung geprüft", result=result
                    )
                except (
                    httpx.HTTPError,
                    HTTPException,
                    ValueError,
                    OSError,
                    InvalidTag,
                    TypeError,
                    RecursionError,
                ):
                    report.update(status="failed", message="Verbindung oder Zugang prüfen")
            lock(db)
            db.refresh(row)
            if row.revision != revision:
                raise HTTPException(409, "Integration während Prüfung geändert; Ergebnis verworfen")
            row.last_check = encode(report)
            db.commit()
            return integration_info(cfg, row)

    @app.get("/api/integration-bindings/{scope}/{owner_id}")
    def selection(scope: Scope, owner_id: UUID, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            binding_owner(db, scope, str(owner_id))
            return binding_info(db, scope, str(owner_id))

    @app.put("/api/integration-bindings/{scope}/{owner_id}")
    def select_integrations(
        scope: Scope, owner_id: UUID, body: BindingInput, auth: Auth
    ) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            lock(db)
            if body.selection_mode == "inherit" and scope != "conversation":
                raise HTTPException(422, "Vererbung gilt nur für Projektgespräche")
            binding_owner(db, scope, str(owner_id))
            if scope == "task":
                active = db.scalar(
                    select(TaskRun.id)
                    .where(
                        TaskRun.task_id == str(owner_id),
                        TaskRun.status.in_(("queued", "running", "awaiting_approval")),
                    )
                    .limit(1)
                )
            else:
                query = select(Run.id).join(Conversation, Run.conversation_id == Conversation.id)
                query = (
                    query.where(Conversation.id == str(owner_id))
                    if scope == "conversation"
                    else query.where(Conversation.project_id == str(owner_id))
                )
                active = db.scalar(
                    query.where(Run.status.in_(("queued", "routing", "streaming"))).limit(1)
                )
            if active:
                raise HTTPException(409, "Aktiven Lauf erst abschließen oder stoppen")
            row = db.get(IntegrationBinding, (scope, str(owner_id)))
            if (row.revision if row else 0) != body.expected_revision:
                raise HTTPException(409, "Integrationsauswahl geändert; neu laden")
            ids = [str(item) for item in body.integration_ids]
            found = list(db.scalars(select(Integration).where(Integration.id.in_(ids))))
            if len(found) != len(ids):
                raise HTTPException(404, "Ausgewählte Integration nicht vorhanden")
            if not row:
                row = IntegrationBinding(scope=scope, owner_id=str(owner_id), revision=1)
                db.add(row)
            else:
                row.revision += 1
            row.integration_ids, row.selection_mode = encode(ids), body.selection_mode
            db.commit()
            return binding_info(db, scope, str(owner_id))
