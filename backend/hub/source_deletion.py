"""Confirmed deletion of one local project source, with durable byte cleanup."""

import hashlib
import json
import time
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from hub import db as models
from hub.config import Settings
from hub.db_locks import ownership_lock
from hub.deletion import DeletionInput, references


def plan(db: Session, project_id: str, source_id: str) -> dict[str, Any]:
    from hub.use_cases import project_case_witness

    project = db.get(models.Project, project_id)
    source = db.get(models.Source, source_id)
    if not project or not source or source.project_id != project_id:
        raise HTTPException(404, "Quelle im Projekt nicht gefunden")
    chunks = list(
        db.scalars(select(models.SourceChunk).where(models.SourceChunk.source_id == source_id))
    )
    events = list(
        db.scalars(
            select(models.SourceReadyEvent).where(models.SourceReadyEvent.source_id == source_id)
        )
    )
    documents = list(
        db.scalars(
            select(models.KnowledgeDocument).where(models.KnowledgeDocument.source_id == source_id)
        )
    )
    connections = list(
        db.scalars(
            select(models.KnowledgeConnection).where(
                models.KnowledgeConnection.project_id == project_id
            )
        )
    )
    blockers = []
    if source.status in {"queued", "extracting"}:
        blockers.append("Die Quelle wird noch verarbeitet. Abschluss abwarten.")
    if any(c.status == "indexing" for c in connections):
        blockers.append("Der Wissensabgleich läuft. Abschluss abwarten.")
    active_runs = [
        run
        for run, conversation in db.execute(
            select(models.Run, models.Conversation)
            .join(models.Conversation)
            .where(models.Run.status.in_({"queued", "routing", "streaming"}))
        )
        if conversation.project_id == project_id or references(run.context_snapshot, {source_id})
    ]
    case_state = project_case_witness(db, project_id)
    if active_runs or case_state.get("active_runs", 0):
        blockers.append("Eine Projektantwort oder ein KI Use Case läuft noch. Abschluss abwarten.")
    ids = {source_id}
    revisions = list(db.scalars(select(models.ArtifactRevision)))
    if any(r.status in {"queued", "rendering"} and references(r.spec, ids) for r in revisions):
        blockers.append(
            "Eine Projektdatei mit dieser Quelle wird noch erzeugt. Abschluss abwarten."
        )
    actions = list(
        db.scalars(
            select(models.ActionIntent).where(
                models.ActionIntent.status.in_({"proposed", "approved"})
            )
        )
    )
    if any(references(a.parameters, ids) for a in actions):
        blockers.append(
            "Eine vorbereitete Systemaktion verwendet die Quelle. Aktion zuerst widerrufen."
        )
    task_revisions = list(
        db.scalars(
            select(models.TaskRevision).join(
                models.Task,
                (models.TaskRevision.task_id == models.Task.id)
                & (models.TaskRevision.revision == models.Task.revision),
            )
        )
    )
    task_runs = list(
        db.scalars(
            select(models.TaskRun).where(
                models.TaskRun.status.in_({"queued", "running", "awaiting_approval"})
            )
        )
    )
    schedules = list(
        db.scalars(
            select(models.TaskSchedule)
            .join(
                models.Task,
                (models.TaskSchedule.task_id == models.Task.id)
                & (models.TaskSchedule.task_revision == models.Task.revision),
            )
            .where(models.TaskSchedule.paused.is_(False))
        )
    )
    grants = list(
        db.scalars(
            select(models.TaskWriteGrant).where(
                models.TaskWriteGrant.expires > time.time(),
                models.TaskWriteGrant.revoked.is_(False),
                models.TaskWriteGrant.used.is_(False),
            )
        )
    )
    grant_revisions = [db.get(models.TaskRevision, (g.task_id, g.task_revision)) for g in grants]
    binding_revisions = []
    for binding in db.scalars(
        select(models.WorkflowBinding).where(models.WorkflowBinding.status != "revoked")
    ):
        task = db.get(models.Task, binding.task_id)
        pending = db.scalar(
            select(models.WorkflowDispatch).where(
                models.WorkflowDispatch.binding_id == binding.id,
                models.WorkflowDispatch.status.in_({"prepared", "uncertain"}),
            )
        )
        if task and (
            (
                binding.task_revision == task.revision
                and binding.control_revision == task.control_revision
            )
            or pending
        ):
            binding_revisions.append(
                db.get(models.TaskRevision, (binding.task_id, binding.task_revision))
            )
    if (
        any(
            references(r.spec, ids)
            for r in [*task_revisions, *grant_revisions, *binding_revisions]
            if r
        )
        or any(references(r.snapshot, {source_id, project_id}) for r in task_runs)
        or any(references(s.definition, ids) for s in schedules)
    ):
        blockers.append(
            "Eine aktuelle Aufgabe oder aktive Freigabe verwendet die Quelle. "
            "Bezug zuerst entfernen beziehungsweise Freigabe widerrufen."
        )
    counts = dict(
        sources=1,
        source_revisions=source.revision,
        chunks=len(chunks),
        linked_knowledge_documents=len(documents),
    )
    preserved = [
        "Andere Quellen, Projekte und Gespräche bleiben erhalten.",
        "Gespeicherte Antworten, Quellenangaben und abgeschlossene Ausgaben bleiben erhalten; "
        "die gelöschte Quelle kann daraus nicht mehr geöffnet werden.",
        "Bereits heruntergeladene Dateien und Sicherungen bleiben erhalten.",
    ]
    if documents:
        preserved.append(
            "Nur die lokale Wissenskopie wird entfernt. Externes Original und Verbindung bleiben "
            "erhalten; ein erneuter Wissensabgleich kann die Quelle wieder importieren."
        )
    owned = [project, source, *chunks, *events, *documents, *connections]
    state = sorted(
        (
            r.__tablename__,
            json.dumps({c.name: getattr(r, c.name) for c in r.__table__.columns}, sort_keys=True),
        )
        for r in owned
    )
    witness = hashlib.sha256(
        json.dumps([state, blockers, counts], sort_keys=True).encode()
    ).hexdigest()
    return dict(
        kind="source",
        id=source_id,
        project_id=project_id,
        name=source.name,
        expected_state=witness,
        counts=counts,
        blockers=blockers,
        preserved=preserved,
        _source=source,
        _events=events,
    )


def preview(db: Session, project_id: str, source_id: str) -> dict[str, Any]:
    return {k: v for k, v in plan(db, project_id, source_id).items() if not k.startswith("_")}


def permanently_delete(
    db: Session, cfg: Settings, project_id: str, source_id: str, body: DeletionInput
) -> dict[str, Any]:
    from hub.deletion_cleanup import queue_cleanup
    from hub.task_api import lock

    ownership_lock(db)
    lock(db)
    p = plan(db, project_id, source_id)
    if p["blockers"]:
        raise HTTPException(409, " ".join(p["blockers"]))
    if body.expected_state != p["expected_state"]:
        raise HTTPException(
            409, "Inhalte inzwischen geändert. Löschvorschau neu öffnen und erneut bestätigen."
        )
    cleanup_id = queue_cleanup(db, [p["_source"]], [])
    event_by_id = {e.id: e for e in p["_events"]}
    for occurrence in db.scalars(
        select(models.TaskEventOccurrence).where(
            models.TaskEventOccurrence.event_id.in_(event_by_id)
        )
    ):
        event = event_by_id[occurrence.event_id]
        if not occurrence.deleted_event_snapshot:
            occurrence.deleted_event_snapshot = json.dumps(
                {c.name: getattr(event, c.name) for c in event.__table__.columns}, sort_keys=True
            )
        occurrence.event_id = None
    db.flush()
    db.execute(
        delete(models.SourceReadyEvent).where(models.SourceReadyEvent.source_id == source_id)
    )
    db.execute(
        delete(models.KnowledgeDocument).where(models.KnowledgeDocument.source_id == source_id)
    )
    db.execute(delete(models.SourceChunk).where(models.SourceChunk.source_id == source_id))
    db.execute(delete(models.Source).where(models.Source.id == source_id))
    db.commit()
    return dict(ok=True, cleanup_id=cleanup_id, deleted_source_id=source_id, project_id=project_id)
