"""Manual read-only task vertical. No scheduler, model code or external dispatch."""

import asyncio
import json
import time
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException
from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import TOOLS, StrictInput, digest, encode
from hub.config import Settings
from hub.db import (
    Project,
    ScheduleOccurrence,
    Skill,
    SkillRevision,
    Source,
    Task,
    TaskRevision,
    TaskRun,
    TaskSchedule,
    TaskStep,
)
from hub.knowledge_api import Auth
from hub.n8n_drafts import connection_draft
from hub.skill_api import eligible, sha


class Binding(StrictInput):
    id: UUID
    revision: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReadStep(StrictInput):
    tool_id: Literal["hub.inspect", "ha.inspect", "ha.backups.inspect", "ha.maintenance.plan"] = (
        "hub.inspect"
    )
    tool_revision: Literal[1] = 1
    parameters: StrictInput = Field(default_factory=StrictInput)


class AnalyzeStep(StrictInput):
    tool_id: Literal["ai.analyze"]
    tool_revision: Literal[1] = 1
    parameters: StrictInput = Field(default_factory=StrictInput)


def default_steps() -> list[ReadStep | AnalyzeStep]:
    return [ReadStep()]


class TaskSpec(StrictInput):
    title: str = Field(min_length=1, max_length=160)
    goal: str = Field(min_length=1, max_length=4000)
    project_id: UUID | None = None
    sources: list[Binding] = Field(default_factory=list, max_length=8)
    skills: list[Binding] = Field(default_factory=list, max_length=3)
    timezone: str = Field(default="Europe/Berlin", max_length=80)
    trigger: Literal["manual"] = "manual"
    autonomy: Literal["analyze_only"] = "analyze_only"
    label: Literal["LOCAL_ONLY"] = "LOCAL_ONLY"
    steps: list[ReadStep | AnalyzeStep] = Field(
        default_factory=default_steps, min_length=1, max_length=5
    )
    success_criterion: Literal["all_reads_completed"] = "all_reads_completed"
    output: Literal["task_center"] = "task_center"
    max_cost_usd: Literal[0] = 0
    timeout_seconds: int = Field(default=15, ge=1, le=30)

    @model_validator(mode="after")
    def model_step_last(self) -> "TaskSpec":
        analyses = [i for i, step in enumerate(self.steps) if step.tool_id == "ai.analyze"]
        if analyses and analyses != [len(self.steps) - 1]:
            raise ValueError("At most one local analysis, as the final step")
        external = [s for s in self.steps if s.tool_id.startswith("ha.")]
        if len(external) > 1 or (external and analyses):
            raise ValueError("One fixed HA report per task; no implicit model context transfer")
        return self

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        return value


class EditInput(StrictInput):
    spec: TaskSpec
    expected_revision: int = Field(ge=1)
    expected_control_revision: int = Field(ge=1)


class ControlInput(StrictInput):
    expected_revision: int = Field(ge=1)
    expected_control_revision: int = Field(ge=1)
    paused: bool
    archived: bool = False


class RunInput(StrictInput):
    request_id: UUID
    expected_revision: int = Field(ge=1)
    expected_control_revision: int = Field(ge=1)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def lock(db: Session) -> None:
    # Independent namespace: neither Vault nor Skill mutations are held here.
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.execute(text("SELECT pg_advisory_xact_lock(791103045)"))


def current(db: Session, task_id: str) -> tuple[Task, TaskRevision, TaskSpec]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    revision = db.get(TaskRevision, (task.id, task.revision))
    if revision is None or digest(revision.spec) != revision.sha256:
        raise HTTPException(409, "Aufgabenvorgabe beschädigt")
    try:
        spec = TaskSpec.model_validate_json(revision.spec)
    except ValidationError:
        raise HTTPException(409, "Aufgabenvorgabe nicht mehr unterstützt") from None
    return task, revision, spec


def check_bindings(db: Session, spec: TaskSpec) -> dict[str, Any]:
    project_id = str(spec.project_id) if spec.project_id else None
    if project_id:
        project = db.get(Project, project_id)
        if project is None or project.archived:
            raise HTTPException(409, "Aufgabenprojekt fehlt oder archiviert")
    for group in (spec.sources, spec.skills):
        if len({b.id for b in group}) != len(group):
            raise HTTPException(422, "Doppelte Kontextbindung")
    for binding in spec.sources:
        source = db.get(Source, str(binding.id))
        if (
            source is None
            or not project_id
            or source.project_id != project_id
            or source.status != "ready"
            or source.revision != binding.revision
            or source.sha256 != binding.sha256
            or source.label != "LOCAL_ONLY"
        ):
            raise HTTPException(409, "Quellenbindung geändert oder außerhalb des Projekts")
    checked = []
    for binding in spec.skills:
        skill = db.get(Skill, str(binding.id))
        revision = db.get(SkillRevision, (str(binding.id), binding.revision))
        if (
            skill is None
            or revision is None
            or skill.revision != binding.revision
            or revision.sha256 != binding.sha256
            or revision.sha256 != sha(revision.document)
            or not eligible(skill, revision, project_id)
        ):
            raise HTTPException(
                409, "Skillbindung geändert, deaktiviert oder außerhalb des Projekts"
            )
        checked.append({**binding.model_dump(mode="json"), "document": revision.document})
    for step in spec.steps:
        if step.tool_id == "ai.analyze":
            continue  # Fixed local text analysis; never a model-selected external tool.
        tool = TOOLS.get(step.tool_id)
        if (
            tool is None
            or tool["revision"] != step.tool_revision
            or tool["effect"] != "read"
            or (
                tool["external"]
                and step.tool_id not in ("ha.inspect", "ha.backups.inspect", "ha.maintenance.plan")
            )
        ):
            raise HTTPException(409, "Lesewerkzeugrevision nicht mehr verfügbar")
    return {
        "spec": spec.model_dump(mode="json"),
        "skills_checked": checked,
        "model": None,
        "cost_usd": 0,
        "label": "LOCAL_ONLY",
    }


def task_info(db: Session, task_id: str) -> dict[str, Any]:
    task, revision, spec = current(db, task_id)
    last = db.scalar(
        select(TaskRun)
        .where(TaskRun.task_id == task.id)
        .order_by(TaskRun.created.desc(), TaskRun.id.desc())
        .limit(1)
    )
    from hub.schedule_api import schedule_info

    plan = db.get(TaskSchedule, task.id)
    return {
        "id": task.id,
        "revision": task.revision,
        "control_revision": task.control_revision,
        "paused": task.paused,
        "archived": task.archived,
        "spec": spec.model_dump(mode="json"),
        "spec_sha256": revision.sha256,
        "created": task.created,
        "schedule": schedule_info(db, task),
        "next_run": plan.next_due if plan else None,
        "last_run": {"id": last.id, "status": last.status, "created": last.created}
        if last
        else None,
    }


def run_info(db: Session, run: TaskRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "task_revision": run.task_revision,
        "control_revision": run.control_revision,
        "status": run.status,
        "error": run.error,
        "created": run.created,
        "finished": run.finished,
        "snapshot": json.loads(run.snapshot),
        "steps": [
            {
                "sequence": s.sequence,
                "tool_id": s.tool_id,
                "result": json.loads(s.result),
                "finished": s.finished,
            }
            for s in db.scalars(
                select(TaskStep).where(TaskStep.run_id == run.id).order_by(TaskStep.sequence)
            )
        ],
    }


def check_schedule(db: Session, run: TaskRun) -> None:
    occurrence = db.scalar(select(ScheduleOccurrence).where(ScheduleOccurrence.run_id == run.id))
    if occurrence is None:
        return  # Manual task runs retain their existing authorization path.
    plan = db.get(TaskSchedule, run.task_id)
    if plan is None or plan.paused or plan.revision != occurrence.schedule_revision:
        raise HTTPException(409, "Zeitplan pausiert oder geändert")


def execute_task_read(
    factory: sessionmaker[Session], run_id: str, cfg: Settings | None = None
) -> None:
    with factory() as db:
        lock(db)
        run = db.get(TaskRun, run_id)
        if run is None or run.status != "queued":
            return  # Persisted receipt or cancellation wins, including duplicate delivery.
        try:
            check_schedule(db, run)
            task, revision, spec = current(db, run.task_id)
            if (
                task.paused
                or task.archived
                or task.revision != run.task_revision
                or task.control_revision != run.control_revision
            ):
                raise HTTPException(409, "Aufgabe pausiert, archiviert oder inzwischen geändert")
            try:
                snapshot = json.loads(run.snapshot)
                valid_snapshot = digest(
                    encode(snapshot["spec"])
                ) == revision.sha256 and snapshot == check_bindings(db, spec)
            except (ValueError, KeyError, TypeError):
                valid_snapshot = False
            if not valid_snapshot:
                raise HTTPException(409, "Laufvorgabe verändert")
            if any(step.tool_id == "ai.analyze" for step in spec.steps):
                raise HTTPException(409, "Modellschritt benötigt den lokalen Analyseworker")
            started = time.monotonic()
            for sequence, step in enumerate(spec.steps, 1):
                if time.monotonic() - started > spec.timeout_seconds:
                    raise HTTPException(409, "Aufgabenzeitgrenze erreicht")
                # Fixed read adapter. Goal, documents and metadata never become code.
                if step.tool_id.startswith("ha."):
                    from hub.ha_backups import inspect as backups
                    from hub.ha_maintenance import inspect as maintenance
                    from hub.home_assistant import inspect as health

                    adapter = {
                        "ha.inspect": health,
                        "ha.backups.inspect": backups,
                        "ha.maintenance.plan": maintenance,
                    }[step.tool_id]
                    result = adapter(cfg or Settings.from_env())
                else:
                    result = {
                        "projects": db.scalar(select(func.count()).select_from(Project)),
                        "sources": db.scalar(select(func.count()).select_from(Source)),
                        "label": "LOCAL_ONLY",
                    }
                if time.monotonic() - started > spec.timeout_seconds:
                    raise HTTPException(409, "Aufgabenzeitgrenze nach Leseprüfung erreicht")
                db.add(
                    TaskStep(
                        run_id=run.id,
                        sequence=sequence,
                        tool_id=step.tool_id,
                        result=encode(result),
                    )
                )
            run.status = "succeeded"
        except HTTPException as error:
            run.status, run.error = "failed", str(error.detail)
        run.finished = time.time()
        db.commit()  # Local reads and receipts are atomic; no external side effect to retry.


def install_task_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/tasks")
    def listing(auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            return [
                task_info(db, t.id) for t in db.scalars(select(Task).order_by(Task.created.desc()))
            ]

    @app.post("/api/tasks")
    def create(spec: TaskSpec, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            check_bindings(db, spec)
            task = Task()
            db.add(task)
            db.flush()
            document = encode(spec.model_dump(mode="json"))
            db.add(
                TaskRevision(task_id=task.id, revision=1, spec=document, sha256=digest(document))
            )
            db.commit()
            return task_info(db, task.id)

    @app.patch("/api/tasks/{task_id}")
    def edit(task_id: str, body: EditInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            task, _, _ = current(db, task_id)
            if (
                task.revision != body.expected_revision
                or task.control_revision != body.expected_control_revision
            ):
                raise HTTPException(409, "Aufgabe inzwischen geändert; Entwurf bleibt erhalten")
            if task.archived:
                raise HTTPException(409, "Archivierte Aufgabe zuerst wiederherstellen")
            check_bindings(db, body.spec)
            task.revision += 1
            task.control_revision += 1
            task.paused = True
            document = encode(body.spec.model_dump(mode="json"))
            db.add(
                TaskRevision(
                    task_id=task.id, revision=task.revision, spec=document, sha256=digest(document)
                )
            )
            db.commit()
            return task_info(db, task_id)

    @app.patch("/api/tasks/{task_id}/control")
    def control(task_id: str, body: ControlInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            task, _, spec = current(db, task_id)
            if (
                task.revision != body.expected_revision
                or task.control_revision != body.expected_control_revision
            ):
                raise HTTPException(409, "Aufgabenstatus inzwischen geändert")
            if body.archived and not body.paused:
                raise HTTPException(422, "Archivierte Aufgaben bleiben pausiert")
            if not body.paused:
                check_bindings(db, spec)
            if task.paused != body.paused or task.archived != body.archived:
                task.paused, task.archived = body.paused, body.archived
                task.control_revision += 1
            db.commit()
            return task_info(db, task_id)

    @app.post("/api/tasks/{task_id}/runs")
    async def start(task_id: str, body: RunInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            request_digest = digest(encode({"task_id": task_id, **body.model_dump(mode="json")}))
            previous = db.scalar(select(TaskRun).where(TaskRun.request_key == str(body.request_id)))
            if previous:
                if previous.request_digest != request_digest:
                    raise HTTPException(409, "Anfrage-ID gehört zu anderem Aufgabenlauf")
                return run_info(db, previous)
            task, revision, spec = current(db, task_id)
            if (
                task.paused
                or task.archived
                or task.revision != body.expected_revision
                or task.control_revision != body.expected_control_revision
                or revision.sha256 != body.spec_sha256
            ):
                raise HTTPException(409, "Geprüfte Aufgabe nicht aktuell oder pausiert")
            if db.scalar(
                select(TaskRun.id).where(
                    TaskRun.task_id == task_id, TaskRun.status.in_(["queued", "running"])
                )
            ):
                raise HTTPException(409, "Für diese Aufgabe läuft bereits ein Lauf")
            snapshot = check_bindings(db, spec)
            run = TaskRun(
                task_id=task_id,
                task_revision=task.revision,
                control_revision=task.control_revision,
                request_key=str(body.request_id),
                request_digest=request_digest,
                snapshot=encode(snapshot),
            )
            db.add(run)
            db.flush()
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

    @app.get("/api/tasks/{task_id}/runs")
    def runs(task_id: str, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            current(db, task_id)
            return [
                run_info(db, r)
                for r in db.scalars(
                    select(TaskRun)
                    .where(TaskRun.task_id == task_id)
                    .order_by(TaskRun.created.desc(), TaskRun.id.desc())
                    .limit(100)
                )
            ]

    @app.post("/api/task-runs/{run_id}/cancel")
    def cancel(run_id: str, body: StrictInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            run = db.get(TaskRun, run_id)
            if run is None:
                raise HTTPException(404, "Aufgabenlauf fehlt")
            if run.status == "queued":
                run.status, run.finished = "cancelled", time.time()
                db.commit()
            elif run.status == "running":
                run.error = "Abbruch angefordert"
                db.commit()
            elif run.status != "cancelled":
                raise HTTPException(409, "Aufgabenlauf bereits abgeschlossen")
            return run_info(db, run)

    @app.get("/api/tasks/{task_id}/revisions")
    def revisions(task_id: str, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            current(db, task_id)
            return [
                {"revision": r.revision, "sha256": r.sha256, "spec": json.loads(r.spec)}
                for r in db.scalars(
                    select(TaskRevision)
                    .where(TaskRevision.task_id == task_id)
                    .order_by(TaskRevision.revision)
                )
            ]

    @app.get("/api/tasks/{task_id}/n8n-check-draft")
    def draft(task_id: str, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            task, revision, _ = current(db, task_id)
            return {
                "workflow": connection_draft(task.id, task.revision, revision.sha256),
                "purpose": "connection_check_only",
                "executes_task": False,
                "contains_private_context": False,
                "label": "LOCAL_ONLY",
            }
