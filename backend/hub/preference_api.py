"""Authenticated, CAS-protected response style scopes."""

import json
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput
from hub.db import Conversation, Project, ResponsePreference, ResponsePreferenceRevision
from hub.db_locks import ownership_lock
from hub.knowledge_api import Auth
from hub.preferences import Overrides, digest, resolve, stored
from hub.skill_api import lock


class PreferenceInput(StrictInput):
    expected_revision: int = Field(ge=0)
    overrides: Overrides


def install_preference_api(app: FastAPI, factory: sessionmaker[Session]) -> None:
    def scope(
        db: Session, kind: str, identifier: str, *, writing: bool = False
    ) -> tuple[str, Conversation | None, str | None]:
        if kind == "global":
            return "global", None, None
        if kind == "projects":
            project = db.get(Project, identifier)
            if project is None or project.kind != "project" or (writing and project.archived):
                raise HTTPException(404, "Projektraum nicht gefunden")
            return "project:" + identifier, None, identifier
        conversation = db.get(Conversation, identifier)
        if conversation is None or (writing and conversation.archived):
            raise HTTPException(404, "Aktives Gespräch nicht gefunden")
        return "conversation:" + identifier, conversation, None

    def view(db: Session, kind: str, identifier: str, *, writing: bool = False) -> dict[str, Any]:
        key, conversation, project_id = scope(db, kind, identifier, writing=writing)
        try:
            revision, values = stored(db, key)
            resolved = resolve(db, conversation, project_id=project_id)
        except ValueError:
            raise HTTPException(409, "Antwortvorgaben konnten nicht gelesen werden") from None
        return {"revision": revision, "overrides": values, **resolved}

    def save(db: Session, kind: str, identifier: str, body: PreferenceInput) -> dict[str, Any]:
        ownership_lock(db)
        lock(db)
        current = view(db, kind, identifier, writing=True)
        if current["revision"] != body.expected_revision:
            raise HTTPException(409, "Antwortvorgaben inzwischen geändert; neu laden")
        key, _, _ = scope(db, kind, identifier, writing=True)
        values = body.overrides.model_dump(exclude_none=True)
        revision = body.expected_revision + 1
        head = db.get(ResponsePreference, key)
        if head is None:
            db.add(ResponsePreference(key=key, revision=revision))
        else:
            head.revision = revision
        db.add(
            ResponsePreferenceRevision(
                key=key, revision=revision, overrides=json.dumps(values), sha256=digest(values)
            )
        )
        db.commit()
        return view(db, kind, identifier)

    @app.get("/api/preferences/global")
    def global_get(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return view(db, "global", "")

    @app.put("/api/preferences/global")
    def global_put(body: PreferenceInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return save(db, "global", "", body)

    @app.get("/api/preferences/{kind}/{identifier}")
    def scoped_get(
        kind: Literal["projects", "conversations"], identifier: UUID, auth: Auth
    ) -> dict[str, Any]:
        with factory() as db:
            return view(db, kind, str(identifier))

    @app.put("/api/preferences/{kind}/{identifier}")
    def scoped_put(
        kind: Literal["projects", "conversations"],
        identifier: UUID,
        body: PreferenceInput,
        auth: Auth,
    ) -> dict[str, Any]:
        with factory() as db:
            return save(db, kind, str(identifier), body)
