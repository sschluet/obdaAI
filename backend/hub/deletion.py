"""Confirmed permanent deletion of app-owned objects, preserving external originals."""

import hashlib
import json
import time
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from hub import db as models
from hub.config import Settings
from hub.db_locks import MEMORY_INDEX, ownership_lock
from hub.integrations import IntegrationBinding


class DeletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_state: str = Field(pattern=r"^[0-9a-f]{64}$")


def references(document: str, ids: set[str]) -> bool:
    """Only exact JSON values (including tagged source ids), never prose substring matches."""
    try:
        value = json.loads(document)
    except (ValueError, TypeError):
        return False

    def walk(item: Any) -> bool:
        if isinstance(item, str):
            return item in ids or any(
                item == prefix + ident for ident in ids for prefix in ("skill:", "message:", "run:")
            )
        if isinstance(item, dict):
            return any(walk(v) for v in item.values())
        if isinstance(item, list):
            return any(walk(v) for v in item)
        return False

    return walk(value)


def plan(
    db: Session,
    kind: Literal["project", "conversation"],
    identifier: str,
    cfg: Settings | None = None,
    *,
    allow_use_case: bool = False,
) -> dict[str, Any]:
    from hub.use_cases import project_case_witness

    target: Any = db.get(models.Project if kind == "project" else models.Conversation, identifier)
    if not target or (kind == "conversation" and target.purpose != "chat" and not allow_use_case):
        raise HTTPException(
            404, "Projekt nicht gefunden" if kind == "project" else "Gespräch nicht gefunden"
        )
    chats = list(
        db.scalars(
            select(models.Conversation).where(
                models.Conversation.project_id == identifier
                if kind == "project"
                else models.Conversation.id == identifier
            )
        )
    )
    chat_ids = [c.id for c in chats]
    integration_bindings = list(
        db.scalars(
            select(IntegrationBinding).where(
                (
                    (IntegrationBinding.scope == "conversation")
                    & IntegrationBinding.owner_id.in_(chat_ids)
                )
                | (
                    (IntegrationBinding.scope == "project")
                    & (IntegrationBinding.owner_id == identifier)
                    & (kind == "project")
                )
            )
        )
    )
    case_state = (
        project_case_witness(db, identifier)
        if kind == "project"
        else {"use_cases": 0, "use_case_runs": 0, "state": []}
    )
    runs = list(db.scalars(select(models.Run).where(models.Run.conversation_id.in_(chat_ids))))
    messages = list(
        db.scalars(select(models.Message).where(models.Message.conversation_id.in_(chat_ids)))
    )
    sources = (
        list(db.scalars(select(models.Source).where(models.Source.project_id == identifier)))
        if kind == "project"
        else []
    )
    artifacts = (
        list(db.scalars(select(models.Artifact).where(models.Artifact.project_id == identifier)))
        if kind == "project"
        else []
    )
    skills = (
        list(db.scalars(select(models.Skill).where(models.Skill.project_id == identifier)))
        if kind == "project"
        else []
    )
    artifact_ids = [a.id for a in artifacts]
    revisions = list(
        db.scalars(
            select(models.ArtifactRevision).where(
                models.ArtifactRevision.artifact_id.in_(artifact_ids)
            )
        )
    )
    source_ids = [s.id for s in sources]
    events = list(
        db.scalars(
            select(models.SourceReadyEvent).where(models.SourceReadyEvent.source_id.in_(source_ids))
        )
    )
    keys = ["conversation:" + c.id for c in chats] + (
        ["project:" + identifier] if kind == "project" else []
    )
    prefs = list(
        db.scalars(
            select(models.ResponsePreferenceRevision).where(
                models.ResponsePreferenceRevision.key.in_(keys)
            )
        )
    )
    blockers = []
    if kind == "project" and target.kind != "project":
        blockers.append(
            "Verbundene Wissensräume können hier nicht gelöscht werden. Verbindung unter Wissen "
            "verwalten."
        )
    if case_state.get("active_runs", 0):
        blockers.append("Ein KI Use Case läuft noch. Lauf zuerst abbrechen und Abschluss abwarten.")
    if any(r.status in {"queued", "routing", "streaming"} for r in runs):
        blockers.append(
            "Eine Antwort wird noch erzeugt. Lauf zuerst abbrechen und seinen Abschluss abwarten."
        )
    if any(s.status in {"queued", "extracting"} for s in sources):
        blockers.append("Eine Quelldatei wird noch verarbeitet. Abschluss abwarten.")
    if any(r.status in {"queued", "rendering"} for r in revisions):
        blockers.append("Eine Projektdatei wird noch erzeugt. Abschluss abwarten.")
    ids = {
        identifier,
        *chat_ids,
        *[r.id for r in runs],
        *[m.id for m in messages],
        *source_ids,
        *artifact_ids,
        *[s.id for s in skills],
    }
    for action in db.scalars(
        select(models.ActionIntent).where(models.ActionIntent.status.in_({"proposed", "approved"}))
    ):
        if references(action.parameters, ids):
            blockers.append(
                "Eine vorbereitete Systemaktion verwendet dieses Projekt. Aktion zuerst widerrufen."
            )
            break
    # Current bindings remain live; older versions and completed runs are independent history.
    dependent_tasks = set()
    tasks = {task.id: task for task in db.scalars(select(models.Task))}
    current_revisions = list(
        db.scalars(
            select(models.TaskRevision).join(
                models.Task,
                (models.TaskRevision.task_id == models.Task.id)
                & (models.TaskRevision.revision == models.Task.revision),
            )
        )
    )
    for task_revision in current_revisions:
        if references(task_revision.spec, ids):
            dependent_tasks.add(task_revision.task_id)
    for run in db.scalars(
        select(models.TaskRun).where(
            models.TaskRun.status.in_({"queued", "running", "awaiting_approval"})
        )
    ):
        if references(run.snapshot, ids):
            dependent_tasks.add(run.task_id)
    for schedule in db.scalars(select(models.TaskSchedule)):
        task = tasks.get(schedule.task_id)
        if task and schedule.task_revision == task.revision and not schedule.paused:
            if references(schedule.definition, ids):
                dependent_tasks.add(schedule.task_id)
    for grant in db.scalars(
        select(models.TaskWriteGrant).where(
            models.TaskWriteGrant.expires > time.time(),
            models.TaskWriteGrant.revoked.is_(False),
            models.TaskWriteGrant.used.is_(False),
        )
    ):
        grant_revision = db.get(models.TaskRevision, (grant.task_id, grant.task_revision))
        if grant_revision and references(grant_revision.spec, ids):
            dependent_tasks.add(grant.task_id)
    for binding in db.scalars(
        select(models.WorkflowBinding).where(models.WorkflowBinding.status != "revoked")
    ):
        task = tasks.get(binding.task_id)
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
            binding_revision = db.get(models.TaskRevision, (binding.task_id, binding.task_revision))
            if binding_revision and references(binding_revision.spec, ids):
                dependent_tasks.add(binding.task_id)
    if dependent_tasks:
        blockers.append(
            "Gespeicherte Aufgaben oder aktive Freigaben verweisen auf diese Inhalte. "
            "Aktuelle Aufgabenbezüge ändern beziehungsweise Freigaben widerrufen."
        )
    if kind == "project":
        if db.scalar(
            select(models.Memory).where(
                models.Memory.project_id == identifier, models.Memory.deleted.is_(False)
            )
        ):
            blockers.append(
                "Vault-Erinnerungen sind mit diesem Projekt verknüpft. Zuordnung im Vault zuerst "
                "entfernen."
            )
        if db.scalar(
            select(models.KnowledgeConnection).where(
                models.KnowledgeConnection.project_id == identifier
            )
        ):
            blockers.append(
                "Eine externe Wissensverbindung ist mit diesem Projekt verknüpft. Verbindung "
                "zuerst unter Wissen entfernen."
            )
        if db.scalar(
            select(models.KnowledgeDocument).where(
                models.KnowledgeDocument.source_id.in_(source_ids)
            )
        ):
            blockers.append(
                "Eine externe Wissensverbindung verwendet eine Projektquelle. Verbindung zuerst "
                "unter Wissen entfernen."
            )
    for other_artifact in db.scalars(
        select(models.ArtifactRevision).where(
            ~models.ArtifactRevision.artifact_id.in_(artifact_ids)
        )
    ):
        # Exporting a chat into a project file must preserve that independently saved file.
        # chat_metadata is provenance only; its absent chat is an intentional permanent deletion.
        if references(other_artifact.spec, ids):
            blockers.append(
                "Eine andere Projektdatei verwendet diese Quellen. Abhängige Datei zuerst "
                "entfernen oder Projekt archivieren."
            )
            break
    for other_chat in db.scalars(
        select(models.Conversation).where(~models.Conversation.id.in_(chat_ids))
    ):
        if references(other_chat.skill_selection or "[]", ids):
            blockers.append(
                "Ein anderes Gespräch hat einen Projektskill ausgewählt. Skillauswahl dort "
                "zuerst ändern."
            )
            break
    for other_pref in db.scalars(
        select(models.ResponsePreferenceRevision).where(
            ~models.ResponsePreferenceRevision.key.in_(keys)
        )
    ):
        if references(other_pref.overrides, ids):
            blockers.append(
                "Andere Antwort-Einstellungen verweisen auf einen Projektskill. Skillauswahl "
                "dort zuerst ändern."
            )
            break
    origins = {"chat:" + m.id for m in messages}
    retained_notes = [
        note
        for note in db.scalars(select(models.Memory))
        if note.origin in origins or any(note.origin.startswith(prefix + ":") for prefix in origins)
    ]
    chat_research = list(
        db.scalars(select(models.Research).where(models.Research.id.in_([r.id for r in runs])))
    )
    retained_research = set()
    for revision in db.scalars(select(models.ArtifactRevision)):
        for research in chat_research:
            if references(revision.draft_metadata, {research.id}):
                retained_research.add(research.id)
    counts = dict(
        conversations=len(chats),
        messages=len(messages),
        runs=len(runs),
        sources=len(sources),
        artifacts=len(artifacts),
        skills=len(skills),
        preferences=len(prefs),
        retained_memories=len(retained_notes),
        retained_research=len(retained_research) if kind == "conversation" else 0,
        integration_bindings=len(integration_bindings),
        use_cases=case_state["use_cases"],
        use_case_runs=case_state["use_case_runs"],
    )
    # Hash every persisted column: editing, new runs, new revisions and status changes invalidate
    # confirmation.
    owned = [
        target,
        *chats,
        *runs,
        *messages,
        *sources,
        *artifacts,
        *skills,
        *revisions,
        *events,
        *prefs,
        *integration_bindings,
    ]
    owned.extend(
        db.scalars(
            select(models.Research).where(
                models.Research.project_id == identifier
                if kind == "project"
                else models.Research.id.in_([r.id for r in runs])
            )
        )
    )
    owned.extend(
        db.scalars(
            select(models.SkillRevision).where(
                models.SkillRevision.skill_id.in_([skill.id for skill in skills])
            )
        )
    )
    state = sorted(
        (
            row.__tablename__,
            json.dumps(
                {col.name: getattr(row, col.name) for col in row.__table__.columns}, sort_keys=True
            ),
        )
        for row in owned
    )
    witness = hashlib.sha256(
        json.dumps([state, case_state["state"], blockers, counts], sort_keys=True).encode()
    ).hexdigest()
    return dict(
        kind=kind,
        id=identifier,
        name=target.name if kind == "project" else target.title,
        project_id=identifier if kind == "project" else target.project_id,
        expected_state=witness,
        counts=counts,
        blockers=blockers,
        preserved=[
            "Externe Originaldateien und Vault bleiben erhalten."
            if kind == "project"
            else "Gespeicherte Projektdateien bleiben erhalten.",
            "Historische Aufgabenfassungen und abgeschlossene Aufgabenläufe bleiben erhalten.",
            "Bereits heruntergeladene Exporte und bestehende Sicherungen bleiben erhalten.",
            "Bereits gelöschte Vault-Erinnerungen bleiben als historische Daten erhalten.",
        ],
        _chats=chats,
        _runs=runs,
        _sources=sources,
        _artifacts=artifacts,
        _revisions=revisions,
        _skills=skills,
        _keys=keys,
        _target=target,
        _research_ids=[r.id for r in chat_research if r.id not in retained_research],
        _source_events=events,
    )


def preview(
    db: Session,
    kind: Literal["project", "conversation"],
    identifier: str,
    cfg: Settings | None = None,
    *,
    allow_use_case: bool = False,
) -> dict[str, Any]:
    return {
        k: v
        for k, v in plan(db, kind, identifier, cfg, allow_use_case=allow_use_case).items()
        if not k.startswith("_")
    }


def permanently_delete(
    db: Session,
    cfg: Settings,
    kind: Literal["project", "conversation"],
    identifier: str,
    body: DeletionInput | None,
    *,
    allow_use_case: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    # Serialize scoped writers before validating the confirmation witness.
    from hub.task_api import lock
    from hub.use_cases import delete_project_cases

    ownership_lock(db)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(791103050)"))
    if kind == "project" and db.scalar(
        select(models.Memory.id).where(models.Memory.project_id == identifier).limit(1)
    ):
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": MEMORY_INDEX}):
                raise HTTPException(
                    409, "Vault-Abgleich läuft. Projektlöschung nach Abschluss erneut versuchen."
                )
    # Internal Use-Case cleanup can already hold a SQLite write transaction.
    # A second BEGIN IMMEDIATE would fail; that transaction already owns the writer lock.
    sqlite_writer = (
        db.bind is not None
        and db.bind.dialect.name == "sqlite"
        and bool(getattr(db.connection().connection.driver_connection, "in_transaction", False))
    )
    if not sqlite_writer:
        lock(db)
    p = plan(db, kind, identifier, cfg, allow_use_case=allow_use_case)
    if p["blockers"]:
        raise HTTPException(409, " ".join(p["blockers"]))
    if body and body.expected_state != p["expected_state"]:
        raise HTTPException(
            409, "Inhalte inzwischen geändert. Löschvorschau neu öffnen und erneut bestätigen."
        )
    from hub.deletion_cleanup import queue_cleanup

    cleanup_id = queue_cleanup(db, p["_sources"], p["_revisions"])
    try:
        chat_ids = [c.id for c in p["_chats"]]
        db.execute(
            delete(IntegrationBinding).where(
                (IntegrationBinding.scope == "conversation")
                & IntegrationBinding.owner_id.in_(chat_ids)
            )
        )
        if kind == "project":
            db.execute(
                delete(IntegrationBinding).where(
                    (IntegrationBinding.scope == "project")
                    & (IntegrationBinding.owner_id == identifier)
                )
            )
            delete_project_cases(db, identifier, cfg)
        run_ids = [r.id for r in p["_runs"]]
        db.execute(delete(models.RunEvent).where(models.RunEvent.run_id.in_(run_ids)))
        db.execute(delete(models.Message).where(models.Message.conversation_id.in_(chat_ids)))
        db.execute(delete(models.Research).where(models.Research.id.in_(p["_research_ids"])))
        db.execute(delete(models.Run).where(models.Run.conversation_id.in_(chat_ids)))
        db.execute(
            delete(models.ResponsePreferenceRevision).where(
                models.ResponsePreferenceRevision.key.in_(p["_keys"])
            )
        )
        db.execute(
            delete(models.ResponsePreference).where(models.ResponsePreference.key.in_(p["_keys"]))
        )
        db.execute(delete(models.Conversation).where(models.Conversation.id.in_(chat_ids)))
        if kind == "project":
            source_ids = [s.id for s in p["_sources"]]
            artifact_ids = [a.id for a in p["_artifacts"]]
            skill_ids = [s.id for s in p["_skills"]]
            db.execute(
                delete(models.ArtifactRevision).where(
                    models.ArtifactRevision.artifact_id.in_(artifact_ids)
                )
            )
            db.execute(delete(models.Artifact).where(models.Artifact.id.in_(artifact_ids)))
            db.execute(
                delete(models.SkillRevision).where(models.SkillRevision.skill_id.in_(skill_ids))
            )
            db.execute(delete(models.Skill).where(models.Skill.id.in_(skill_ids)))
            event_by_id = {event.id: event for event in p["_source_events"]}
            for occurrence in db.scalars(
                select(models.TaskEventOccurrence).where(
                    models.TaskEventOccurrence.event_id.in_(event_by_id)
                )
            ):
                event = event_by_id[occurrence.event_id]
                if not occurrence.deleted_event_snapshot:
                    occurrence.deleted_event_snapshot = json.dumps(
                        {
                            column.name: getattr(event, column.name)
                            for column in event.__table__.columns
                        },
                        sort_keys=True,
                    )
                occurrence.event_id = None
            db.flush()
            db.execute(
                delete(models.SourceReadyEvent).where(
                    models.SourceReadyEvent.project_id == identifier
                )
            )
            db.execute(
                delete(models.SourceChunk).where(models.SourceChunk.source_id.in_(source_ids))
            )
            db.execute(delete(models.Source).where(models.Source.project_id == identifier))
            db.execute(delete(models.Research).where(models.Research.project_id == identifier))
            db.execute(delete(models.Project).where(models.Project.id == identifier))
        if commit:
            db.commit()
        else:
            db.flush()
    except Exception:
        db.rollback()
        raise
    return dict(
        ok=True,
        cleanup_id=cleanup_id,
        deleted_conversation_ids=chat_ids,
        deleted_project_id=identifier if kind == "project" else None,
    )
