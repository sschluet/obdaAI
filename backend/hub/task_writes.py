"""Task-bound authority for one reversible local write. No model-selected actions."""

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, HTTPException
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput, archive_write, digest, encode, info
from hub.config import Settings
from hub.db import (
    ActionGrant,
    ActionIntent,
    ActionPolicy,
    ActionReceipt,
    TaskActionLink,
    TaskRun,
    TaskWriteGrant,
    TaskWriteGrantEvent,
)
from hub.knowledge_api import Auth

if TYPE_CHECKING:
    from hub.task_api import TaskSpec


class WriteAuthorityInput(StrictInput):
    task_revision: int = Field(ge=1)
    control_revision: int = Field(ge=1)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_revision: int = Field(ge=1)
    ttl_seconds: int = Field(default=300, ge=15, le=3600)


def policy_lock(db: Session) -> ActionPolicy:
    # Task lock is already held. Do not start a second SQLite transaction.
    policy = db.scalar(select(ActionPolicy).where(ActionPolicy.id == 1).with_for_update())
    if policy is None:
        raise HTTPException(503, "Aktionsschema fehlt")
    return policy


def grant_info(db: Session, task_id: str) -> dict[str, Any] | None:
    grant = db.get(TaskWriteGrant, task_id)
    if grant is None:
        return None
    return {
        "task_revision": grant.task_revision,
        "control_revision": grant.control_revision,
        "spec_sha256": grant.spec_sha256,
        "policy_revision": grant.policy_revision,
        "expires": grant.expires,
        "revoked": grant.revoked,
        "used": grant.used,
        "max_writes": 1,
    }


def grant_event(db: Session, grant: TaskWriteGrant, event: str, run_id: str | None = None) -> None:
    db.flush()
    document = encode({"event": event, "run_id": run_id, **(grant_info(db, grant.task_id) or {})})
    db.add(TaskWriteGrantEvent(task_id=grant.task_id, document=document, sha256=digest(document)))


def approval_info(db: Session, run: TaskRun) -> dict[str, Any]:
    policy = db.get(ActionPolicy, 1)
    links = db.scalars(
        select(TaskActionLink)
        .where(TaskActionLink.run_id == run.id)
        .order_by(TaskActionLink.sequence)
    )
    actions = []
    for link in links:
        row = db.get(ActionIntent, link.action_id)
        if row is None:
            raise HTTPException(409, "Aufgabenaktionsbeleg fehlt")
        actions.append(info(db, row))
    return {
        "policy": {"paused": policy.paused, "revision": policy.revision} if policy else None,
        "actions": actions,
    }


def write_action(db: Session, run: TaskRun, spec: "TaskSpec", sequence: int) -> ActionIntent:
    step = spec.steps[sequence - 1]
    if step.tool_id != "project.archive":
        raise HTTPException(409, "Aufgaben-Schreibaktion nicht unterstützt")
    params = encode(step.parameters.model_dump(mode="json"))
    key = str(uuid5(NAMESPACE_URL, "obdaai:task-action:" + run.id + ":" + str(sequence)))
    row = db.get(ActionIntent, key)
    if row is None:
        policy = policy_lock(db)
        row = ActionIntent(
            id=key,
            request_key=key,
            tool_id=step.tool_id,
            tool_revision=step.tool_revision,
            parameters=params,
            parameters_sha256=digest(params),
            policy_revision=policy.revision,
            label="LOCAL_ONLY",
        )
        db.add(row)
        db.flush()
        db.add(TaskActionLink(action_id=row.id, run_id=run.id, sequence=sequence))
        db.flush()
    link = db.get(TaskActionLink, row.id)
    if (
        row.tool_id != step.tool_id
        or row.tool_revision != step.tool_revision
        or row.parameters != params
        or row.parameters_sha256 != digest(params)
        or row.label != "LOCAL_ONLY"
        or link is None
        or link.run_id != run.id
        or link.sequence != sequence
    ):
        raise HTTPException(409, "Aufgabenaktion verändert")
    return row


def bounded_grant(db: Session, run: TaskRun) -> TaskWriteGrant:
    from hub.task_api import current

    policy = policy_lock(db)
    _, revision, spec = current(db, run.task_id)
    grant = db.get(TaskWriteGrant, run.task_id)
    if (
        policy.paused
        or spec.autonomy != "bounded_autonomous"
        or grant is None
        or grant.revoked
        or grant.used
        or grant.expires <= time.time()
        or grant.task_revision != run.task_revision
        or grant.control_revision != run.control_revision
        or grant.spec_sha256 != revision.sha256
        or grant.policy_revision != policy.revision
    ):
        raise HTTPException(403, "Keine aktuelle begrenzte Aufgabenfreigabe")
    return grant


def prepare_run(db: Session, run: TaskRun, spec: "TaskSpec") -> None:
    if spec.autonomy == "analyze_only":
        return
    if spec.autonomy == "bounded_autonomous":
        bounded_grant(db, run)
    for sequence, step in enumerate(spec.steps, 1):
        if step.tool_id == "project.archive":
            write_action(db, run, spec, sequence)
    if spec.autonomy == "confirm_each":
        run.status = "awaiting_approval"


def archive_step(db: Session, run: TaskRun, spec: "TaskSpec", sequence: int) -> dict[str, Any]:
    row = write_action(db, run, spec, sequence)
    if db.get(ActionReceipt, row.id):
        raise HTTPException(409, "Aufgabenbeleg bereits vorhanden; kein zweiter Write")
    policy = policy_lock(db)
    if spec.autonomy == "bounded_autonomous":
        grant = bounded_grant(db, run)
        if row.status != "proposed" or db.get(ActionGrant, row.id) is not None:
            raise HTTPException(409, "Begrenzte Aufgabenaktion nicht mehr unverbraucht")
        row.policy_revision, row.status = policy.revision, "approved"
        db.add(
            ActionGrant(
                action_id=row.id,
                parameters_sha256=row.parameters_sha256,
                tool_revision=row.tool_revision,
                policy_revision=policy.revision,
                expires=grant.expires,
            )
        )
        db.flush()
        grant.used = True
        grant_event(db, grant, "consumed", run.id)
    elif spec.autonomy != "confirm_each":
        raise HTTPException(403, "Schreibprofil fehlt")
    result = archive_write(db, row, policy)
    db.add(ActionReceipt(action_id=row.id, result=encode(result)))
    row.status = "succeeded"
    return {**result, "action_id": row.id, "label": "LOCAL_ONLY", "effect": "write"}


def checked_run(db: Session, run: TaskRun, body: WriteAuthorityInput) -> "TaskSpec":
    from hub.task_api import check_bindings, check_schedule, current

    task, revision, spec = current(db, run.task_id)
    if (
        task.paused
        or task.archived
        or run.task_revision != task.revision
        or run.control_revision != task.control_revision
        or body.task_revision != task.revision
        or body.control_revision != task.control_revision
        or body.spec_sha256 != revision.sha256
    ):
        raise HTTPException(409, "Aufgabenfreigabe passt nicht zum aktuellen Lauf")
    check_schedule(db, run)
    try:
        valid = json.loads(run.snapshot) == check_bindings(db, spec)
    except (ValueError, TypeError, ValidationError):
        valid = False
    if not valid:
        raise HTTPException(409, "Aufgabenmanifest verändert")
    policy = policy_lock(db)
    if policy.paused or policy.revision != body.policy_revision:
        raise HTTPException(409, "Autonome Änderungen pausiert oder Freigabestand geändert")
    return spec


def install_task_writes(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.post("/api/tasks/{task_id}/write-grant")
    def grant(task_id: str, body: WriteAuthorityInput, auth: Auth) -> dict[str, Any]:
        from hub.task_api import check_bindings, current, lock, task_info

        with factory() as db:
            lock(db)
            task, revision, spec = current(db, task_id)
            if (
                spec.autonomy != "bounded_autonomous"
                or task.paused
                or task.archived
                or task.revision != body.task_revision
                or task.control_revision != body.control_revision
                or revision.sha256 != body.spec_sha256
            ):
                raise HTTPException(
                    409, "Aktuelle aktivierte Aufgabe mit begrenztem Profil erforderlich"
                )
            check_bindings(db, spec)
            policy = policy_lock(db)
            if policy.paused or policy.revision != body.policy_revision:
                raise HTTPException(409, "Aktionspause oder Policy geändert")
            old = db.get(TaskWriteGrant, task.id)
            if old and not old.used and not old.revoked and old.expires > time.time():
                raise HTTPException(409, "Bestehende Freigabe zuerst widerrufen")
            if old:
                db.delete(old)
                db.flush()
            db.add(
                TaskWriteGrant(
                    task_id=task.id,
                    task_revision=task.revision,
                    control_revision=task.control_revision,
                    spec_sha256=revision.sha256,
                    policy_revision=policy.revision,
                    expires=time.time() + body.ttl_seconds,
                )
            )
            db.flush()
            granted = db.get(TaskWriteGrant, task.id)
            assert granted is not None
            grant_event(db, granted, "granted")
            db.commit()
            return task_info(db, task.id)

    @app.get("/api/tasks/{task_id}/write-grant/history")
    def history(task_id: str, auth: Auth) -> list[dict[str, Any]]:
        from hub.task_api import current

        with factory() as db:
            current(db, task_id)
            result = []
            for event in db.scalars(
                select(TaskWriteGrantEvent)
                .where(TaskWriteGrantEvent.task_id == task_id)
                .order_by(TaskWriteGrantEvent.created.desc(), TaskWriteGrantEvent.id.desc())
                .limit(100)
            ):
                if digest(event.document) != event.sha256:
                    raise HTTPException(409, "Freigabehistorie verändert")
                result.append({**json.loads(event.document), "created": event.created})
            return result

    @app.post("/api/tasks/{task_id}/write-grant/revoke")
    def revoke(task_id: str, body: StrictInput, auth: Auth) -> dict[str, Any]:
        from hub.task_api import current, lock, task_info

        with factory() as db:
            lock(db)
            current(db, task_id)
            policy_lock(db)
            grant = db.get(TaskWriteGrant, task_id)
            if grant and not grant.revoked:
                grant.revoked = True
                grant_event(db, grant, "revoked")
            db.commit()
            return task_info(db, task_id)

    @app.post("/api/task-runs/{run_id}/approve")
    async def approve(run_id: str, body: WriteAuthorityInput, auth: Auth) -> dict[str, Any]:
        from hub.task_api import lock, run_info

        with factory() as db:
            lock(db)
            run = db.get(TaskRun, run_id)
            if run is None:
                raise HTTPException(404, "Aufgabenlauf fehlt")
            if run.status != "awaiting_approval":
                raise HTTPException(409, "Lauf wartet nicht auf Freigabe; Status prüfen")
            spec = checked_run(db, run, body)
            if spec.autonomy != "confirm_each":
                raise HTTPException(409, "Einzelfreigabeprofil fehlt")
            for sequence, step in enumerate(spec.steps, 1):
                if step.tool_id != "project.archive":
                    continue
                row = write_action(db, run, spec, sequence)
                if row.status != "proposed" or db.get(ActionGrant, row.id) is not None:
                    raise HTTPException(409, "Aufgabenaktion bereits freigegeben oder widerrufen")
                row.policy_revision, row.status = body.policy_revision, "approved"
                db.add(
                    ActionGrant(
                        action_id=row.id,
                        parameters_sha256=row.parameters_sha256,
                        tool_revision=row.tool_revision,
                        policy_revision=body.policy_revision,
                        expires=time.time() + body.ttl_seconds,
                    )
                )
            run.status = "queued"
            if not cfg.database_url.startswith("sqlite"):
                from hub.jobs import enqueue_task_read

                enqueue_task_read(db, cfg, run.id)
            db.commit()
            result = run_info(db, run)
        if cfg.database_url.startswith("sqlite"):
            from hub.task_model import execute_task

            job = asyncio.create_task(execute_task(factory, cfg, run.id, app.state.providers))
            app.state.tasks.add(job)
            job.add_done_callback(app.state.tasks.discard)
        return result
