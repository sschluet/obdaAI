"""n8n supplies clock pulses; the Hub alone authorizes and records local task runs."""

import asyncio
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from datetime import date as CalendarDate
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput, digest, encode
from hub.config import Settings, read_secret
from hub.db import ScheduleOccurrence, ScheduleRevision, SchedulerPulse, Task, TaskRun, TaskSchedule
from hub.knowledge_api import Auth
from hub.task_api import check_bindings, current, lock


class ScheduleDefinition(StrictInput):
    kind: Literal["manual", "once", "daily", "weekly"]
    timezone: str = Field(default="Europe/Berlin", max_length=80)
    time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    date: CalendarDate | None = None
    weekdays: list[int] = Field(default_factory=list, max_length=7)

    @field_validator("timezone")
    @classmethod
    def zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unbekannte Zeitzone") from None
        return value

    @model_validator(mode="after")
    def shape(self) -> "ScheduleDefinition":
        if self.kind == "once":
            if self.date is None or self.weekdays:
                raise ValueError("Einmalige Termine benötigen ein Datum und keine Wochentage")
            wall = datetime.combine(self.date, datetime.strptime(self.time, "%H:%M").time())
            if len(wall_instants(wall, self.timezone)) != 1:
                raise ValueError("Uhrzeit durch Zeitumstellung ungültig oder doppeldeutig")
        elif self.date is not None:
            raise ValueError("Wiederkehrende Termine haben kein einmaliges Datum")
        if self.kind == "weekly":
            if (
                not self.weekdays
                or len(set(self.weekdays)) != len(self.weekdays)
                or any(day < 0 or day > 6 for day in self.weekdays)
            ):
                raise ValueError("Bitte unterschiedliche Wochentage auswählen")
        elif self.weekdays:
            raise ValueError("Wochentage nur für wöchentliche Termine")
        return self


def wall_instants(wall: datetime, timezone: str) -> list[float]:
    zone = ZoneInfo(timezone)
    instants = set()
    for fold in (0, 1):
        aware = wall.replace(tzinfo=zone, fold=fold)
        if datetime.fromtimestamp(aware.timestamp(), zone).replace(tzinfo=None) == wall:
            instants.add(aware.timestamp())
    return sorted(instants)


def next_due(definition: ScheduleDefinition, after: float) -> float | None:
    if definition.kind == "manual":
        return None
    local = datetime.fromtimestamp(after, ZoneInfo(definition.timezone))
    clock = datetime.strptime(definition.time, "%H:%M").time()
    days = (
        [definition.date]
        if definition.kind == "once"
        else [local.date() + timedelta(days=offset) for offset in range(9)]
    )
    for day in days:
        assert day is not None
        if definition.kind == "weekly" and day.weekday() not in definition.weekdays:
            continue
        times = wall_instants(datetime.combine(day, clock), definition.timezone)
        # Recurrent spring gaps are skipped; autumn repeats run once at the first instant.
        if times and times[0] > after:
            return times[0]
    return None


class ScheduleInput(StrictInput):
    definition: ScheduleDefinition
    expected_revision: int = Field(ge=1)
    expected_control_revision: int = Field(ge=1)
    expected_schedule_revision: int = Field(ge=0)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ScheduleControl(StrictInput):
    expected_schedule_revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    expected_control_revision: int = Field(ge=1)
    paused: bool


def schedule_info(db: Session, task: Task) -> dict[str, Any] | None:
    plan = db.get(TaskSchedule, task.id)
    if plan is None:
        return None
    changed = task.revision != plan.task_revision or task.control_revision != plan.control_revision
    return {
        "revision": plan.revision,
        "definition": json.loads(plan.definition),
        "paused": plan.paused or task.paused or task.archived or changed,
        "needs_review": changed,
        "next_due": plan.next_due,
        "error": "Aufgabe geändert; Zeitplan erneut prüfen" if changed else plan.error,
        "completed": plan.next_due is None and not plan.paused,
    }


def configured(cfg: Settings) -> bool:
    if not cfg.scheduler_enabled or not cfg.scheduler_token_file:
        return False
    try:
        return len(read_secret(cfg.scheduler_token_file)) >= 32
    except (OSError, ValueError):
        return False


def scheduler_status(db: Session, cfg: Settings, now: float) -> dict[str, Any]:
    pulse = db.get(SchedulerPulse, 1)
    enabled = configured(cfg)
    return {
        "configured": enabled,
        "last_tick": pulse.last_tick if pulse else None,
        "healthy": enabled and pulse is not None and 0 <= now - pulse.last_tick <= 180,
    }


def tick(db: Session, cfg: Settings, now: float) -> list[str]:
    """Called under the task transaction lock. No external side effect before commit."""
    pulse = db.get(SchedulerPulse, 1)
    if pulse is None:
        db.add(SchedulerPulse(id=1, last_tick=now))
    else:
        pulse.last_tick = now
    jobs = []
    plans = list(
        db.scalars(
            select(TaskSchedule).where(TaskSchedule.paused.is_(False), TaskSchedule.next_due <= now)
        )
    )
    for plan in plans:
        due = plan.next_due
        assert due is not None
        occurrence = ScheduleOccurrence(
            task_id=plan.task_id, schedule_revision=plan.revision, due=due, status="skipped"
        )
        db.add(occurrence)
        definition = ScheduleDefinition.model_validate_json(plan.definition)
        plan.next_due = next_due(definition, now)
        try:
            task, revision, spec = current(db, plan.task_id)
            if (
                task.paused
                or task.archived
                or task.revision != plan.task_revision
                or task.control_revision != plan.control_revision
                or revision.sha256 != plan.spec_sha256
            ):
                raise HTTPException(409, "Aufgabe pausiert, archiviert oder geändert")
            snapshot = check_bindings(db, spec)
            if now - due >= 120:
                occurrence.reason = "Termin verpasst; kein automatisches Nachholen"
                continue
            if db.scalar(
                select(TaskRun.id).where(
                    TaskRun.task_id == task.id, TaskRun.status.in_(["queued", "running"])
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
                    encode({"task_id": task.id, "schedule_revision": plan.revision, "due": due})
                ),
                snapshot=encode(snapshot),
            )
            db.add(run)
            db.flush()
            occurrence.run_id, occurrence.status = run.id, "queued"
            if not cfg.database_url.startswith("sqlite"):
                from hub.jobs import enqueue_task_read

                enqueue_task_read(db, cfg, run.id)
            jobs.append(run.id)
        except HTTPException as error:
            plan.paused, plan.error = True, str(error.detail)[:240]
            occurrence.status, occurrence.reason = "blocked", plan.error
    return jobs


def occurrence_status(db: Session, occurrence: ScheduleOccurrence) -> str:
    run = db.get(TaskRun, occurrence.run_id) if occurrence.run_id else None
    return run.status if run else occurrence.status


def install_schedule_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/scheduler/status")
    def status(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return scheduler_status(db, cfg, time.time())

    @app.put("/api/tasks/{task_id}/schedule")
    def save(task_id: str, body: ScheduleInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            task, revision, spec = current(db, task_id)
            plan = db.get(TaskSchedule, task_id)
            if (
                task.archived
                or task.revision != body.expected_revision
                or task.control_revision != body.expected_control_revision
                or revision.sha256 != body.spec_sha256
                or (plan.revision if plan else 0) != body.expected_schedule_revision
            ):
                raise HTTPException(409, "Aufgabe oder Zeitplan inzwischen geändert")
            check_bindings(db, spec)
            due = next_due(body.definition, time.time())
            if due is None and body.definition.kind != "manual":
                raise HTTPException(422, "Bitte einen zukünftigen Termin wählen")
            if plan is None:
                plan = TaskSchedule(task_id=task_id, revision=1)
                db.add(plan)
            else:
                plan.revision += 1
            plan.task_revision, plan.control_revision = task.revision, task.control_revision
            plan.spec_sha256, plan.definition = (
                revision.sha256,
                encode(body.definition.model_dump(mode="json")),
            )
            plan.paused, plan.error, plan.next_due = True, None, due
            db.add(
                ScheduleRevision(
                    task_id=task_id,
                    revision=plan.revision,
                    snapshot=encode(
                        {
                            "definition": json.loads(plan.definition),
                            "paused": plan.paused,
                            "task_revision": plan.task_revision,
                            "control_revision": plan.control_revision,
                            "spec_sha256": plan.spec_sha256,
                            "next_due": plan.next_due,
                        }
                    ),
                )
            )
            db.commit()
            from hub.task_api import task_info

            return task_info(db, task_id)

    @app.patch("/api/tasks/{task_id}/schedule/control")
    def control(task_id: str, body: ScheduleControl, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            task, revision, spec = current(db, task_id)
            plan = db.get(TaskSchedule, task_id)
            if (
                plan is None
                or plan.revision != body.expected_schedule_revision
                or task.revision != body.expected_revision
                or task.control_revision != body.expected_control_revision
            ):
                raise HTTPException(409, "Zeitplan oder Aufgabe inzwischen geändert")
            if not body.paused:
                if task.archived:
                    raise HTTPException(409, "Archivierte Aufgabe zuerst wiederherstellen")
                if not scheduler_status(db, cfg, time.time())["healthy"]:
                    raise HTTPException(409, "n8n-Zeitimpuls fehlt; Zeitplan bleibt pausiert")
                check_bindings(db, spec)
                due = next_due(ScheduleDefinition.model_validate_json(plan.definition), time.time())
                if due is None:
                    raise HTTPException(422, "Termin liegt in der Vergangenheit")
                if task.paused:
                    task.paused = False
                    task.control_revision += 1
                plan.task_revision, plan.control_revision = task.revision, task.control_revision
                plan.spec_sha256, plan.next_due, plan.error = revision.sha256, due, None
            plan.paused = body.paused
            plan.revision += 1
            db.add(
                ScheduleRevision(
                    task_id=task_id,
                    revision=plan.revision,
                    snapshot=encode(
                        {
                            "definition": json.loads(plan.definition),
                            "paused": plan.paused,
                            "task_revision": plan.task_revision,
                            "control_revision": plan.control_revision,
                            "spec_sha256": plan.spec_sha256,
                            "next_due": plan.next_due,
                        }
                    ),
                )
            )
            db.commit()
            from hub.task_api import task_info

            return task_info(db, task_id)

    @app.get("/api/tasks/{task_id}/schedule/history")
    def history(task_id: str, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            current(db, task_id)
            return [
                {
                    "id": o.id,
                    "revision": o.schedule_revision,
                    "due": o.due,
                    "status": occurrence_status(db, o),
                    "run_id": o.run_id,
                    "reason": o.reason,
                }
                for o in db.scalars(
                    select(ScheduleOccurrence)
                    .where(ScheduleOccurrence.task_id == task_id)
                    .order_by(ScheduleOccurrence.due.desc())
                    .limit(100)
                )
            ]

    @app.post("/api/scheduler/tick")
    async def pulse(request: Request, body: StrictInput) -> dict[str, int]:
        # Separate machine auth. Browser sessions and CSRF credentials grant no clock access.
        if not configured(cfg):
            raise HTTPException(503, "Zeitplanung nicht eingerichtet")
        header = request.headers.get("authorization", "")
        if not hmac.compare_digest(
            header.encode(), ("Bearer " + read_secret(cfg.scheduler_token_file)).encode()
        ):
            raise HTTPException(401, "Ungültiger Zeitimpuls-Zugang")
        with factory() as db:
            lock(db)
            jobs = tick(db, cfg, datetime.now(UTC).timestamp())
            db.commit()
        if cfg.database_url.startswith("sqlite"):
            from hub.task_model import execute_task

            for run_id in jobs:
                job = asyncio.create_task(execute_task(factory, cfg, run_id, app.state.providers))
                app.state.tasks.add(job)
                job.add_done_callback(app.state.tasks.discard)
        return {"queued": len(jobs)}
