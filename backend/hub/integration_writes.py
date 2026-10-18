"""Human-granted integration writes with durable one-attempt dispatch and reconciliation."""

import json
import time
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import Field, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from hub import integration_write_adapters as adapters
from hub.action_api import (
    TOOLS,
    IntegrationWriteParameters,
    StrictInput,
    digest,
    encode,
    get_action,
    info,
    lock,
)
from hub.config import Settings
from hub.db import ActionGrant, ActionPolicy, ActionReceipt, TaskActionLink
from hub.integration_transport import policy_allows
from hub.integrations import Integration, IntegrationWriteAudit
from hub.knowledge_api import Auth
from hub.provider_settings import decrypt


class PreviewInput(StrictInput):
    expected_revision: int = Field(ge=1)
    operation: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any]


class WriteControl(StrictInput):
    expected_revision: int = Field(ge=1)
    writes_enabled: bool


def registry_lock(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(791103050)"))


def validate_profile(
    db: Session,
    cfg: Settings,
    params: dict[str, Any],
) -> tuple[Integration, dict[str, Any], str, dict[str, Any]]:
    row = db.get(Integration, str(params["integration_id"]))
    if not row or row.revision != params["expected_revision"]:
        raise HTTPException(409, "Integrationsrevision geändert; Vorschau erneuern")
    if not row.enabled or not row.writes_enabled:
        raise HTTPException(403, "Integration oder Schreibaktionen ausgeschaltet")
    config = {**json.loads(row.config), "kind": row.kind}
    if not policy_allows(cfg, config["url"], ssh=row.kind == "ssh"):
        raise HTTPException(403, "Integrationsziel serverseitig nicht freigegeben")
    if not row.encrypted_secret and config["auth"] != "none":
        raise HTTPException(409, "Zugangsdaten fehlen")
    try:
        args = adapters.validate_arguments(row.kind, params["operation"], params["arguments"])
        if len(encode(args).encode()) > 410_000:
            raise ValueError("Arguments exceed bound")
        secret = (
            decrypt(cfg, "integration:" + row.id, row.encrypted_secret)
            if row.encrypted_secret
            else ""
        )
    except (ValueError, ValidationError):
        raise HTTPException(422, "Schreibaktion oder Parameter nicht unterstützt") from None
    return row, config, secret, args


def gate(
    db: Session, cfg: Settings, action_id: str, *, locked: bool = False
) -> tuple[Any, dict[str, Any], str, dict[str, Any]]:
    if not locked:
        registry_lock(db)
        policy = lock(db)
    else:
        current_policy = db.get(ActionPolicy, 1)
        assert current_policy is not None
        policy = current_policy
    row = get_action(db, action_id)
    params = IntegrationWriteParameters.model_validate_json(row.parameters).model_dump(mode="json")
    grant = db.get(ActionGrant, action_id)
    if (
        row.tool_id != "integration.write"
        or row.tool_revision != TOOLS["integration.write"]["revision"]
        or row.label != "LOCAL_ONLY"
        or digest(encode(params)) != row.parameters_sha256
        or db.get(TaskActionLink, action_id)
    ):
        raise HTTPException(409, "Aktionsbindung geändert")
    if (
        policy.paused
        or row.status not in {"approved", "dispatching"}
        or row.policy_revision != policy.revision
        or not grant
        or grant.revoked
        or grant.expires <= time.time()
        or grant.policy_revision != policy.revision
        or grant.tool_revision != row.tool_revision
        or grant.parameters_sha256 != row.parameters_sha256
    ):
        raise HTTPException(403, "Keine aktuelle aktionsgebundene Schreibfreigabe")
    _, config, secret, args = validate_profile(db, cfg, params)
    return row, config, secret, args


def execute_write(factory: sessionmaker[Session], cfg: Settings, action_id: str) -> dict[str, Any]:
    with factory() as db:
        registry_lock(db)
        lock(db)
        row = get_action(db, action_id)
        if db.get(ActionReceipt, action_id) or row.status in {"dispatching", "uncertain"}:
            return info(db, row)  # Never replay a possibly effective external write.
        if row.status != "approved":
            raise HTTPException(403, "Änderung nicht freigegeben")
        row, config, secret, args = gate(db, cfg, action_id, locked=True)
        params = json.loads(row.parameters)
        try:
            before = adapters.snapshot(cfg, config, secret, params["operation"], args)
        except Exception:
            raise HTTPException(502, "Zielzustand nicht lesbar; keine Änderung gestartet") from None
        if digest(encode(before)) != params["expected_state_sha256"]:
            raise HTTPException(409, "Ziel inzwischen geändert; neue Vorschau erforderlich")
        db.add(IntegrationWriteAudit(action_id=action_id, before_state=encode(before)))
        row.status = "dispatching"
        db.commit()  # The intent survives a process failure before/after transmission.
        row, config, secret, args = gate(db, cfg, action_id)
        try:
            acknowledgment = adapters.apply(
                cfg,
                config,
                secret,
                params["operation"],
                args,
                action_id,
                lambda: gate(db, cfg, action_id, locked=True),
            )
            after = (
                acknowledgment
                if config["kind"] == "mcp" and acknowledgment
                else adapters.snapshot(cfg, config, secret, params["operation"], args)
            )
            verified = (
                config["kind"] == "mcp"
                and after.get("acknowledged") is True
                or adapters.matches(config["kind"], params["operation"], args, after)
            )
            result = {
                "label": "LOCAL_ONLY",
                "integration_id": params["integration_id"],
                "operation": params["operation"],
                "before": before,
                "after": after,
                "status": "acknowledged"
                if config["kind"] == "mcp" and verified
                else "verified"
                if verified
                else "uncertain",
                "automatic_retry": False,
            }
            row.status = "succeeded" if verified else "uncertain"
            if verified:
                db.add(ActionReceipt(action_id=action_id, result=encode(result)))
        except Exception:
            # Do not leak credentials, provider payloads, URLs or raw exception strings.
            row.status = "uncertain"
        db.commit()
        return info(db, row)


def install_write_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/integrations/{integration_id}/write-capabilities")
    def capabilities(integration_id: UUID, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            row = db.get(Integration, str(integration_id))
            if not row:
                raise HTTPException(404, "Integration fehlt")
            operations = adapters.capabilities(row.kind)
            return {
                "operations": operations,
                "writes_supported": bool(operations) or row.kind == "smtp",
                "writes_enabled": row.writes_enabled,
                "revision": row.revision,
            }

    @app.patch("/api/integrations/{integration_id}/write-control")
    def control(integration_id: UUID, body: WriteControl, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            registry_lock(db)
            lock(db)
            row = db.get(Integration, str(integration_id))
            if not row or row.revision != body.expected_revision:
                raise HTTPException(409, "Integration geändert")
            if body.writes_enabled and not adapters.capabilities(row.kind) and row.kind != "smtp":
                raise HTTPException(422, "Schreibadapter noch nicht implementiert")
            if row.writes_enabled != body.writes_enabled:
                row.writes_enabled = body.writes_enabled
                row.revision += 1
            db.commit()
            return {"writes_enabled": row.writes_enabled, "revision": row.revision}

    @app.post("/api/integrations/{integration_id}/write-preview")
    def preview(integration_id: UUID, body: PreviewInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            registry_lock(db)
            lock(db)
            params = {"integration_id": str(integration_id), **body.model_dump()}
            row, config, secret, args = validate_profile(db, cfg, params)
            try:
                before = adapters.snapshot(cfg, config, secret, body.operation, args)
            except Exception:
                raise HTTPException(
                    502, "Vorschau nicht lesbar; keine Änderung gestartet"
                ) from None
            return {
                "parameters": {
                    **params,
                    "arguments": args,
                    "expected_state_sha256": digest(encode(before)),
                },
                "preview": {
                    "integration": row.name,
                    "target": config["url"],
                    "operation": body.operation,
                    "before": before,
                    "requested": args,
                    "label": "LOCAL_ONLY",
                },
            }

    @app.post("/api/integrations/{integration_id}/write-catalog")
    def catalog(integration_id: UUID, body: StrictInput, auth: Auth) -> dict[str, Any]:
        from hub.mcp_client import schema_digest

        with factory() as db:
            row = db.get(Integration, str(integration_id))
            if not row or row.kind != "mcp" or not row.enabled or not row.writes_enabled:
                raise HTTPException(403, "Aktives MCP-Schreibprofil erforderlich")
            config = json.loads(row.config)
            if not policy_allows(cfg, config["url"]):
                raise HTTPException(403, "MCP-Ziel nicht freigegeben")
            try:
                secret = (
                    decrypt(cfg, "integration:" + row.id, row.encrypted_secret)
                    if row.encrypted_secret
                    else ""
                )
                result = adapters.mcp_catalog(cfg, config, secret)
            except Exception:
                raise HTTPException(502, "MCP-Katalog nicht lesbar") from None
            return {
                "tools": [
                    {**t, "schema_sha256": schema_digest(t["input_schema"])}
                    for t in result["tools"]
                ],
                "label": "LOCAL_ONLY",
            }

    @app.post("/api/actions/{action_id}/reconcile-integration")
    def reconcile(action_id: UUID, body: StrictInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            registry_lock(db)
            lock(db)
            row = get_action(db, str(action_id))
            if row.tool_id != "integration.write":
                raise HTTPException(422, "Keine Integrationsaktion")
            if db.get(ActionReceipt, row.id):
                return info(db, row)
            if row.status not in {"dispatching", "uncertain"}:
                raise HTTPException(409, "Keine unklare Übertragung")
            params = json.loads(row.parameters)
            _, config, secret, args = validate_profile(db, cfg, params)
            try:
                after = adapters.snapshot(cfg, config, secret, params["operation"], args)
            except Exception:
                raise HTTPException(502, "Abgleich nicht möglich; keine Wiederholung") from None
            if adapters.matches(config["kind"], params["operation"], args, after):
                audit = db.get(IntegrationWriteAudit, row.id)
                db.add(
                    ActionReceipt(
                        action_id=row.id,
                        result=encode(
                            {
                                "status": "observed_matching",
                                "causation_verified": False,
                                "label": "LOCAL_ONLY",
                                "after": after,
                                "before": json.loads(audit.before_state) if audit else None,
                                "automatic_retry": False,
                            }
                        ),
                    )
                )
                row.status = "reconciled"
                db.commit()
            return info(db, row)
