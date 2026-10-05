"""Fixed local actions and one bounded external read adapter.

Human approval is separate from proposals and execution. Local database effects
and receipts commit together. External writes/reconciliation are not implemented.
The optional fixed HA read accepts no model or request-provided target or payload.
"""

import hashlib
import json
import time
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from hub.config import Settings
from hub.db import ActionGrant, ActionIntent, ActionPolicy, ActionReceipt, Project, Source
from hub.home_assistant import inspect as inspect_ha
from hub.knowledge_api import Auth


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArchiveParameters(StrictInput):
    project_id: UUID
    expected_revision: int = Field(ge=1)


class ProposalInput(StrictInput):
    request_id: UUID
    tool_id: str = Field(max_length=80)
    parameters: dict[str, Any]


class GrantInput(StrictInput):
    parameters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_revision: int = Field(ge=1)
    ttl_seconds: int = Field(default=300, ge=15, le=3600)


class PauseInput(StrictInput):
    paused: bool
    expected_revision: int = Field(ge=1)


# These schemas and adapters are code-reviewed, never supplied by a model/document.
TOOLS: dict[str, dict[str, Any]] = {
    "hub.inspect": {
        "id": "hub.inspect",
        "name": "Hub-Status lesen",
        "revision": 1,
        "effect": "read",
        "system": "obdaAI",
        "external": False,
        "parameters_schema": StrictInput.model_json_schema(),
    },
    "ha.inspect": {
        "id": "ha.inspect",
        "name": "Home Assistant prüfen",
        "revision": 1,
        "effect": "read",
        "system": "Home Assistant",
        "external": True,
        "parameters_schema": StrictInput.model_json_schema(),
    },
    "project.archive": {
        "id": "project.archive",
        "name": "Projekt wiederherstellbar archivieren",
        "revision": 1,
        "effect": "write",
        "system": "obdaAI",
        "external": False,
        "parameters_schema": ArchiveParameters.model_json_schema(),
    },
}


def encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def parameters(tool_id: str, value: dict[str, Any]) -> dict[str, Any]:
    try:
        model = ArchiveParameters if tool_id == "project.archive" else StrictInput
        return model.model_validate(value).model_dump(mode="json")
    except ValidationError:
        raise HTTPException(422, "Parameter passen nicht zum festen Werkzeugschema") from None


def lock(db: Session) -> ActionPolicy:
    # Fixed singleton lock orders pause/revocation/approval and the final write.
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    policy = db.scalar(select(ActionPolicy).where(ActionPolicy.id == 1).with_for_update())
    if policy is None:
        raise HTTPException(503, "Aktionsschema fehlt; Migration erforderlich")
    return policy


def info(db: Session, action: ActionIntent) -> dict[str, Any]:
    grant = db.get(ActionGrant, action.id)
    receipt = db.get(ActionReceipt, action.id)
    return {
        "id": action.id,
        "tool_id": action.tool_id,
        "tool_revision": action.tool_revision,
        "parameters": json.loads(action.parameters),
        "parameters_sha256": action.parameters_sha256,
        "label": action.label,
        "policy_revision": action.policy_revision,
        "status": action.status,
        "created": action.created,
        "grant": {"expires": grant.expires, "revoked": grant.revoked} if grant else None,
        "receipt": json.loads(receipt.result) if receipt else None,
    }


def get_action(db: Session, action_id: str) -> ActionIntent:
    action = db.get(ActionIntent, action_id)
    if action is None:
        raise HTTPException(404, "Aktionsvorschlag nicht gefunden")
    return action


def install_action_api(app: FastAPI, factory: sessionmaker[Session], cfg: Settings) -> None:
    @app.get("/api/tools")
    def catalog(auth: Auth) -> list[dict[str, Any]]:
        return [
            {
                **t,
                "configured": t["id"] != "ha.inspect"
                or bool(cfg.ha_token_file and cfg.ha_allowed_ip),
            }
            for t in TOOLS.values()
        ]

    @app.get("/api/home-assistant/status")
    def ha_status(auth: Auth) -> dict[str, Any]:
        return {
            "configured": bool(cfg.ha_token_file and cfg.ha_allowed_ip),
            "writes_enabled": False,
        }

    @app.get("/api/action-policy")
    def policy(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            row = db.get(ActionPolicy, 1)
            if row is None:
                raise HTTPException(503, "Aktionsschema fehlt; Migration erforderlich")
            return {"paused": row.paused, "revision": row.revision}

    @app.patch("/api/action-policy")
    def pause(body: PauseInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            row = lock(db)
            if row.revision != body.expected_revision:
                raise HTTPException(409, "Pausenstatus inzwischen geändert")
            if row.paused != body.paused:
                row.paused, row.revision = body.paused, row.revision + 1
            db.commit()
            return {"paused": row.paused, "revision": row.revision}

    @app.get("/api/actions")
    def listing(auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            return [
                info(db, a)
                for a in db.scalars(
                    select(ActionIntent).order_by(ActionIntent.created.desc()).limit(100)
                )
            ]

    @app.post("/api/actions")
    def propose(body: ProposalInput, auth: Auth) -> dict[str, Any]:
        tool = TOOLS.get(body.tool_id)
        if not tool:
            raise HTTPException(422, "Werkzeug nicht im freigegebenen Katalog")
        params = encode(parameters(body.tool_id, body.parameters))
        with factory() as db:
            policy = lock(db)
            previous = db.scalar(
                select(ActionIntent).where(ActionIntent.request_key == str(body.request_id))
            )
            if previous:
                if previous.tool_id != body.tool_id or previous.parameters != params:
                    raise HTTPException(409, "Anfrage-ID bereits für andere Aktion verwendet")
                return info(db, previous)
            if body.tool_id == "project.archive":
                target = db.get(Project, json.loads(params)["project_id"])
                if target is None:
                    raise HTTPException(404, "Zielprojekt fehlt")
                if target.archived or target.revision != json.loads(params)["expected_revision"]:
                    raise HTTPException(409, "Zielprojekt inzwischen geändert oder archiviert")
            row = ActionIntent(
                request_key=str(body.request_id),
                tool_id=body.tool_id,
                tool_revision=tool["revision"],
                parameters=params,
                parameters_sha256=digest(params),
                label="LOCAL_ONLY",
                policy_revision=policy.revision,
            )
            db.add(row)
            db.commit()
            return info(db, row)

    @app.post("/api/actions/{action_id}/grant")
    def approve(action_id: str, body: GrantInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            policy = lock(db)
            row = get_action(db, action_id)
            if row.status != "proposed" or row.policy_revision != policy.revision:
                raise HTTPException(409, "Vorschlag nicht aktuell; neue Aktion vorbereiten")
            if policy.paused:
                raise HTTPException(409, "Gateway-Schreibaktionen pausiert")
            if (
                body.parameters_sha256 != row.parameters_sha256
                or body.tool_revision != row.tool_revision
            ):
                raise HTTPException(409, "Verglichene Aktion stimmt nicht überein")
            if row.tool_id not in TOOLS or TOOLS[row.tool_id]["effect"] != "write":
                raise HTTPException(409, "Lesewerkzeug benötigt keine Schreibfreigabe")
            db.add(
                ActionGrant(
                    action_id=row.id,
                    parameters_sha256=row.parameters_sha256,
                    tool_revision=row.tool_revision,
                    policy_revision=policy.revision,
                    expires=time.time() + body.ttl_seconds,
                )
            )
            row.status = "approved"
            db.commit()
            return info(db, row)

    @app.post("/api/actions/{action_id}/revoke")
    def revoke(action_id: str, body: StrictInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            row = get_action(db, action_id)
            grant = db.get(ActionGrant, row.id)
            if grant:
                grant.revoked = True
            if row.status != "succeeded":
                row.status = "revoked"
            db.commit()
            return info(db, row)

    @app.post("/api/actions/{action_id}/execute")
    def execute(action_id: str, body: StrictInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            policy = lock(db)
            row = get_action(db, action_id)
            if db.get(ActionReceipt, row.id):
                return info(db, row)  # Read-only receipt replay, even while paused.
            tool = TOOLS.get(row.tool_id)
            if (
                not tool
                or row.tool_revision != tool["revision"]
                or (tool["external"] and row.tool_id != "ha.inspect")
            ):
                raise HTTPException(409, "Werkzeugversion oder Systemgrenze geändert")
            params = parameters(row.tool_id, json.loads(row.parameters))
            if digest(encode(params)) != row.parameters_sha256 or row.label != "LOCAL_ONLY":
                raise HTTPException(409, "Aktionsparameter oder Datenschutzklasse geändert")
            if row.status == "revoked":
                raise HTTPException(403, "Aktionsvorschlag widerrufen")
            if tool["effect"] == "write":
                grant = db.get(ActionGrant, row.id)
                if policy.paused:
                    raise HTTPException(409, "Gateway-Schreibaktionen pausiert")
                if (
                    row.policy_revision != policy.revision
                    or not grant
                    or grant.revoked
                    or grant.expires <= time.time()
                    or grant.policy_revision != policy.revision
                    or grant.parameters_sha256 != row.parameters_sha256
                    or grant.tool_revision != row.tool_revision
                ):
                    raise HTTPException(403, "Keine aktuelle aktionsgebundene Freigabe")
                # No external I/O here: conditional local effect and receipt are one transaction.
                changed = db.execute(
                    update(Project)
                    .where(
                        Project.id == params["project_id"],
                        Project.revision == params["expected_revision"],
                        Project.archived.is_(False),
                    )
                    .values(archived=True, revision=Project.revision + 1)
                )
                if changed.rowcount != 1:  # type: ignore[attr-defined]
                    raise HTTPException(409, "Projektrevision geändert; keine Archivierung")
                result: dict[str, Any] = {
                    "project_id": params["project_id"],
                    "archived": True,
                    "revision": params["expected_revision"] + 1,
                }
            elif row.tool_id == "ha.inspect":
                result = inspect_ha(cfg)
            else:
                result = {
                    "projects": db.scalar(select(func.count()).select_from(Project)),
                    "sources": db.scalar(select(func.count()).select_from(Source)),
                    "label": "LOCAL_ONLY",
                }
            db.add(ActionReceipt(action_id=row.id, result=encode(result)))
            row.status = "succeeded"
            db.commit()
            return info(db, row)
