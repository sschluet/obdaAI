"""Explicit ownership of private artifacts; a missing project is never a scope."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from hub.db import Artifact, Conversation, Project


def owner(
    db: Session,
    project_id: str | None,
    conversation_id: str | None = None,
    *,
    allow_archived_project: bool = False,
) -> Project | Conversation:
    if bool(project_id) == bool(conversation_id):
        raise ValueError("Genau einen Datei-Arbeitsraum angeben")
    if project_id:
        row = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if not row or (row.archived and not allow_archived_project):
            raise ValueError("Aktiver Projektraum fehlt")
        return row
    chat = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    if not chat or chat.archived or chat.purpose != "chat" or chat.memory_scope or chat.project_id:
        raise ValueError("Aktives projektloses Gespräch fehlt")
    return chat


def matches(artifact: Artifact, project_id: str | None, conversation_id: str | None = None) -> bool:
    return (
        bool(project_id) != bool(conversation_id)
        and artifact.project_id == project_id
        and artifact.conversation_id == conversation_id
    )
