"""Action-granted n8n writes with committed intents and read-only reconciliation."""

import json
import re
import time
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import TOOLS, digest, encode, get_action, info, lock, parameters
from hub.config import Settings
from hub.db import ActionGrant, ActionReceipt, WorkflowBinding
from hub.n8n_check import CheckError, remote_check
from hub.n8n_workflows import task_workflow, verify_workflow
from hub.provider_settings import decrypt
from hub.task_api import check_bindings, current
from hub.workflow_api import remote


def validate_binding(db: Session, params: dict[str, Any], tool: str) -> WorkflowBinding:
    b = db.get(WorkflowBinding, str(params["binding_id"]))
    if not b:
        raise HTTPException(404, "Workflowbindung fehlt")
    task, rev, spec = current(db, b.task_id)
    if (
        task.archived
        or task.revision != params["expected_revision"]
        or task.control_revision != params["expected_control_revision"]
        or rev.sha256 != params["spec_sha256"]
        or b.task_revision != task.revision
        or b.spec_sha256 != rev.sha256
    ):
        raise HTTPException(409, "Geprüfte Workflow-/Aufgabenrevision geändert")
    check_bindings(db, spec)
    if tool == "n8n.workflow.activate" and params["workflow_version"] != b.remote_version:
        raise HTTPException(409, "Workflowversion nicht ausdrücklich gebunden")
    if tool == "n8n.workflow.provision" and params["workflow_version"] is not None:
        raise HTTPException(422, "Neuer Workflow besitzt noch keine Version")
    return b


class Finished(Exception):
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result


def gate(db: Session, action_id: str) -> tuple[Any, WorkflowBinding]:
    # Stages committed their intents. Start a fresh transaction, discarding cached
    # policy/grant/task reads. No uncommitted mutation may cross this boundary.
    db.rollback()
    policy = lock(db)
    row = get_action(db, action_id)
    if db.get(ActionReceipt, action_id):
        raise Finished(info(db, row))
    tool = TOOLS.get(row.tool_id)
    grant = db.get(ActionGrant, action_id)
    params = parameters(row.tool_id, json.loads(row.parameters))
    if (
        not tool
        or row.tool_revision != tool["revision"]
        or row.label != "LOCAL_ONLY"
        or digest(encode(params)) != row.parameters_sha256
    ):
        raise HTTPException(409, "Aktionsschema oder Parameter verändert")
    if (
        policy.paused
        or row.status == "revoked"
        or row.policy_revision != policy.revision
        or not grant
        or grant.revoked
        or grant.expires <= time.time()
        or grant.policy_revision != policy.revision
        or grant.parameters_sha256 != row.parameters_sha256
        or grant.tool_revision != row.tool_revision
    ):
        raise HTTPException(403, "Keine aktuelle aktionsgebundene Schreibfreigabe")
    return row, validate_binding(db, params, row.tool_id)


def finish(db: Session, row: Any, b: WorkflowBinding) -> dict[str, Any]:
    result = {
        "binding_id": b.id,
        "workflow_id": b.remote_id,
        "workflow_version": b.remote_version,
        "status": b.status,
        "contains_private_context": False,
        "label": "LOCAL_ONLY",
    }
    db.add(ActionReceipt(action_id=row.id, result=encode(result)))
    row.status = "succeeded"
    db.commit()
    return info(db, row)


def execute_workflow_action(
    factory: sessionmaker[Session], cfg: Settings, action_id: str
) -> dict[str, Any]:
    try:
        return execute_stages(factory, cfg, action_id)
    except Finished as complete:
        return complete.result


def execute_stages(factory: sessionmaker[Session], cfg: Settings, action_id: str) -> dict[str, Any]:
    with factory() as db:
        lock(db)
        row = get_action(db, action_id)
        if db.get(ActionReceipt, row.id):
            return info(db, row)
        if not (
            cfg.n8n_api_key_file
            and cfg.n8n_allowed_ip
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", cfg.n8n_ca_credential_id)
        ):
            raise HTTPException(503, "Begrenzte n8n-Workflowanbindung noch nicht eingerichtet")
        row, b = gate(db, action_id)
        if row.tool_id == "n8n.workflow.activate":
            return activate(db, row, b, cfg)
        if b.status == "verified":
            if not b.graph or not b.remote_id:
                raise HTTPException(409, "Workflowaudit unvollständig")
            verify_workflow(
                remote(cfg, "/api/v1/workflows/" + b.remote_id),
                json.loads(b.graph),
                active=False,
                version=b.remote_version,
            )
            return finish(db, row, b)
        if b.status == "credential_pending":
            raise HTTPException(409, "Credential-Erstellung unklar; kein weiterer POST")
        if b.status == "draft":
            b.status, row.status = "credential_pending", "dispatching"
            bid = b.id
            db.commit()  # Persist before the first possibly effective request.
            row, b = gate(db, action_id)  # Pause/revocation/expiry checked at last boundary.
            try:
                payload = {
                    "name": "obdaAI task " + bid,
                    "type": "httpHeaderAuth",
                    "data": {
                        "name": "X-OBDAAI-WORKFLOW",
                        "value": decrypt(cfg, "workflow:" + bid, b.encrypted_secret),
                    },
                }
                created = remote(cfg, "/api/v1/credentials", payload=payload)
                cid = created.get("id")
                if (
                    not isinstance(cid, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", cid)
                    or created.get("name") != payload["name"]
                    or created.get("type") != payload["type"]
                ):
                    raise CheckError("Unexpected credential creation response")
                b.header_id, b.status = cid, "credential_ready"
                db.commit()
            except (CheckError, httpx.HTTPError, ValueError, OSError):
                row.status = "uncertain"
                db.commit()
                return info(db, row)
        row, b = gate(db, action_id)
        if b.status == "credential_ready":
            if not b.header_id:
                raise HTTPException(409, "Credentialbindung fehlt")
            b.graph = encode(
                task_workflow(
                    b.id, b.task_id, b.task_revision, b.header_id, cfg.n8n_ca_credential_id
                )
            )
            b.status, row.status = "workflow_pending", "dispatching"
            graph = json.loads(b.graph)
            db.commit()
            row, b = gate(db, action_id)
            try:
                created = remote(cfg, "/api/v1/workflows", payload=graph)
                b.remote_id = remote_check(created, graph)
                b.remote_version = created["versionId"]
                b.status = "verified"
                db.commit()
            except (CheckError, httpx.HTTPError, ValueError, OSError):
                row.status = "uncertain"
                db.commit()
                return info(db, row)
        row, b = gate(db, action_id)
        if b.status == "workflow_pending":
            # A lost create response is reconciled by the unique code-owned name.
            assert b.graph
            graph = json.loads(b.graph)
            query = str(
                httpx.QueryParams(
                    {"name": graph["name"], "limit": 100, "excludePinnedData": "true"}
                )
            )
            found = remote(cfg, "/api/v1/workflows?" + query)
            rows = found.get("data")
            if found.get("nextCursor") or not isinstance(rows, list):
                raise HTTPException(409, "Workflowabgleich unvollständig; kein POST")
            matches = [r for r in rows if isinstance(r, dict) and r.get("name") == graph["name"]]
            if len(matches) != 1:
                raise HTTPException(409, "Workflowerstellung unklar; kein weiterer POST")
            b.remote_id = remote_check(matches[0], graph)
            b.remote_version, b.status = matches[0]["versionId"], "verified"
            db.commit()
        row, b = gate(db, action_id)
        if b.status != "verified" or not b.graph or not b.remote_id:
            raise HTTPException(409, "Workflowzustand erfordert Prüfung")
        actual = remote(cfg, "/api/v1/workflows/" + b.remote_id)
        verify_workflow(actual, json.loads(b.graph), active=False, version=b.remote_version)
        return finish(db, row, b)


def activate(db: Session, row: Any, b: WorkflowBinding, cfg: Settings) -> dict[str, Any]:
    if (
        b.status not in ("verified", "activation_pending", "ready")
        or not b.graph
        or not b.remote_id
    ):
        raise HTTPException(409, "Geprüfter unveränderter Workflow erforderlich")
    graph, remote_id, version = json.loads(b.graph), b.remote_id, b.remote_version
    actual = remote(cfg, "/api/v1/workflows/" + remote_id)
    if actual.get("active") is True:
        verify_workflow(actual, graph, active=True, version=version)
        b.status = "ready"
        return finish(db, row, b)
    verify_workflow(actual, graph, active=False, version=version)
    if b.status != "verified":
        raise HTTPException(409, "Veröffentlichung unklar; kein weiterer POST")
    b.status, row.status = "activation_pending", "dispatching"
    action_id = row.id
    db.commit()
    row, b = gate(db, action_id)
    try:
        remote(cfg, "/api/v1/workflows/" + remote_id + "/activate", payload={"versionId": version})
    except (CheckError, httpx.HTTPError, ValueError, OSError):
        row.status = "uncertain"
        db.commit()
        return info(db, row)
    actual = remote(cfg, "/api/v1/workflows/" + remote_id)
    verify_workflow(actual, graph, active=True, version=version)
    b.status = "ready"
    return finish(db, row, b)
