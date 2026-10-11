"""Local document-ready subscriptions; immutable metadata, no dynamic permissions."""

import json
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hub.action_api import digest, encode
from hub.config import Settings
from hub.db import Source, SourceReadyEvent, TaskEventOccurrence, TaskRun, TaskSchedule
from hub.task_api import TaskSpec, check_bindings, current


def record_ready(db: Session, source: Source) -> None:
    # Caller holds the task lock until commit: event IDs cannot be observed out of
    # commit order, and parser retries cannot generate a second readiness event.
    if source.status != "ready" or source.label != "LOCAL_ONLY":
        raise ValueError("Only a ready local original can emit an event")
    existing = db.scalar(
        select(SourceReadyEvent.id).where(
            SourceReadyEvent.source_id == source.id,
            SourceReadyEvent.source_sha256 == source.sha256,
        )
    )
    if existing is None:
        db.add(
            SourceReadyEvent(
                project_id=source.project_id,
                source_id=source.id,
                source_revision=source.revision,
                source_sha256=source.sha256,
            )
        )


def latest_event(db: Session) -> int:
    return db.scalar(select(func.max(SourceReadyEvent.id))) or 0


def validate_subscription(spec: TaskSpec) -> None:
    if (
        not spec.project_id
        or spec.autonomy != "analyze_only"
        or any(step.tool_id not in {"hub.inspect", "ai.analyze"} for step in spec.steps)
    ):
        raise HTTPException(
            422, "Dokumentereignisse benötigen einen Projektraum und lokale Leseschritte"
        )


def check_event(db: Session, event: SourceReadyEvent, project_id: str) -> None:
    source = db.get(Source, event.source_id)
    if (
        event.baseline
        or source is None
        or source.project_id != project_id
        or event.project_id != project_id
        or (
            source.status != "ready"
            or source.label != "LOCAL_ONLY"
            or source.revision != event.source_revision
            or source.sha256 != event.source_sha256
        )
    ):
        raise HTTPException(409, "Auslösendes Dokument nicht mehr bereit oder verändert")


def event_detail(event: SourceReadyEvent) -> dict[str, Any]:
    return {
        "kind": "source_ready",
        "id": event.id,
        "project_id": event.project_id,
        "source_id": event.source_id,
        "revision": event.source_revision,
        "sha256": event.source_sha256,
        "created": event.created,
        "baseline": event.baseline,
    }


def dispatch_events(db: Session, cfg: Settings, now: float) -> list[str]:
    # Called under the same transaction lock as the clock and parser commit.
    jobs: list[str] = []
    budget = 200
    plans = db.scalars(select(TaskSchedule).where(TaskSchedule.paused.is_(False)))
    for plan in plans:
        if json.loads(plan.definition).get("kind") != "source_ready":
            continue
        try:
            task, revision, spec = current(db, plan.task_id)
            validate_subscription(spec)
            if (
                task.paused
                or task.archived
                or task.revision != plan.task_revision
                or (
                    task.control_revision != plan.control_revision
                    or revision.sha256 != plan.spec_sha256
                )
            ):
                raise HTTPException(409, "Aufgabe pausiert, archiviert oder geändert")
            manifest = check_bindings(db, spec)
        except HTTPException as error:
            plan.paused, plan.error = True, str(error.detail)[:240]
            continue
        events = list(
            db.scalars(
                select(SourceReadyEvent)
                .where(
                    SourceReadyEvent.project_id == str(spec.project_id),
                    SourceReadyEvent.id > plan.event_cursor,
                    SourceReadyEvent.created <= now,
                )
                .order_by(SourceReadyEvent.id)
                .limit(min(100, budget))
            )
        )
        for event in events:
            budget -= 1
            plan.event_cursor = event.id
            occurrence = TaskEventOccurrence(
                task_id=task.id,
                schedule_revision=plan.revision,
                event_id=event.id,
                status="skipped",
            )
            db.add(occurrence)
            if event.baseline:
                occurrence.reason = "Vorhandenes Dokument; kein neues Ereignis"
                continue
            try:
                check_event(db, event, str(spec.project_id))
            except HTTPException as error:
                occurrence.reason = str(error.detail)[:240]
                continue
            if now - event.created >= 120:
                occurrence.reason = "Ereignis verpasst; kein automatisches Nachholen"
                continue
            if db.scalar(
                select(TaskRun.id).where(
                    TaskRun.task_id == task.id,
                    TaskRun.status.in_(["queued", "running", "awaiting_approval"]),
                )
            ):
                occurrence.reason = "Vorheriger Lauf noch aktiv; keine parallele Ausführung"
                continue
            run = TaskRun(
                task_id=task.id,
                task_revision=task.revision,
                control_revision=task.control_revision,
                request_key=str(uuid4()),
                request_digest=digest(
                    encode(
                        {
                            "task_id": task.id,
                            "schedule_revision": plan.revision,
                            "event": event_detail(event),
                        }
                    )
                ),
                snapshot=encode(manifest),
            )
            db.add(run)
            db.flush()
            from hub.task_api import freeze_task_integrations

            freeze_task_integrations(db, run, spec)
            occurrence.run_id, occurrence.status = run.id, run.status
            if not cfg.database_url.startswith("sqlite"):
                from hub.jobs import enqueue_task_read

                enqueue_task_read(db, cfg, run.id)
            jobs.append(run.id)
        if budget <= 0:
            break
    return jobs
