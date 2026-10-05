"""Authenticated project artifact drafts, previews, acceptance and immutable versions."""

import asyncio
import json
import time
import uuid
from typing import Annotated, Any

from cryptography.exceptions import InvalidTag
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from hub.artifact_runner import canonical
from hub.artifact_specs import ArtifactSpec
from hub.artifacts import (
    bind_sources,
    checked_manifest,
    digest,
    execute_artifact,
    info,
    output_file,
    reconcile,
    roots,
    spec_for,
    storage_bytes,
)
from hub.auth import require_session
from hub.config import Settings
from hub.db import Artifact, ArtifactRevision, Conversation, LoginSession, Message, Project
from hub.db_locks import ARTIFACT_STORAGE

Auth = Annotated[LoginSession, Depends(require_session)]


class ChatSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    revision: int = Field(ge=1)


class CreateArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    spec: ArtifactSpec
    expected_revision: int | None = Field(default=None, ge=1)
    draft_token: str | None = Field(default=None, min_length=1, max_length=40000, repr=False)
    chat_source: ChatSource | None = None


class AcceptArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_all_pages: bool


def install_artifact_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    def enabled() -> None:
        try:
            roots(cfg)
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc

    def row_for(db: Session, project_id: str, artifact_id: str, revision: int) -> ArtifactRevision:
        project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if not project:
            raise HTTPException(404, "Projekt nicht gefunden")
        artifact = db.get(Artifact, artifact_id)
        row = db.scalar(
            select(ArtifactRevision)
            .where(
                ArtifactRevision.artifact_id == artifact_id,
                ArtifactRevision.revision == revision,
            )
            .with_for_update()
        )
        if not artifact or artifact.project_id != project_id or not row:
            raise HTTPException(404, "Artefaktversion nicht gefunden")
        return row

    def dispatch(db: Session, row: ArtifactRevision) -> None:
        if not cfg.database_url.startswith("sqlite"):
            from hub.jobs import enqueue_artifact

            enqueue_artifact(db, cfg, row.artifact_id, row.revision)

    def create_row(
        db: Session, project_id: str, artifact_id: str | None, body: CreateArtifact
    ) -> tuple[ArtifactRevision, bool]:
        document = canonical(body.spec)
        if len(document.encode()) > 800_000:
            raise HTTPException(413, "Dateiplan ist zu groß")
        replay = db.scalar(
            select(ArtifactRevision).where(ArtifactRevision.request_key == str(body.request_id))
        )
        if replay:
            artifact = db.get(Artifact, replay.artifact_id)
            if (
                not artifact
                or artifact.project_id != project_id
                or (artifact_id is not None and replay.artifact_id != artifact_id)
                or replay.spec_sha256 != digest(document)
                or (artifact_id is None and replay.revision != 1)
            ):
                raise HTTPException(409, "Anfragekennung gehört zu einer anderen Dateiversion")
            return replay, False
        project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if not project or project.archived:
            raise HTTPException(404, "Aktiver Projektraum nicht gefunden")
        try:
            bind_sources(db, cfg, project_id, body.spec)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        chat_metadata = ""
        if body.chat_source:
            chat = db.get(Conversation, str(body.chat_source.conversation_id))
            message = db.scalar(
                select(Message)
                .where(Message.id == str(body.chat_source.message_id))
                .with_for_update()
            )
            if (
                not chat
                or chat.memory_scope
                or (chat.project_id and chat.project_id != project_id)
                or not message
                or message.conversation_id != chat.id
                or not message.active
                or message.role != "assistant"
                or message.revision != body.chat_source.revision
                or not 0 < len(message.content) <= 16000
            ):
                raise HTTPException(409, "Chatantwort oder Projektraum inzwischen geändert")
            chat_metadata = json.dumps(
                {
                    "conversation_id": chat.id,
                    "message_id": message.id,
                    "revision": message.revision,
                    "sha256": digest(message.content),
                    "label": "LOCAL_ONLY",
                    "content": message.content,
                },
                ensure_ascii=False,
            )
        metadata = ""
        if body.draft_token:
            from hub.artifact_drafts import verify_token

            try:
                metadata = verify_token(
                    db,
                    cfg,
                    body.draft_token,
                    project_id,
                    body.spec,
                    artifact_id,
                    body.expected_revision,
                )
            except (ValueError, InvalidTag, KeyError, TypeError):
                raise HTTPException(
                    409, "Dateientwurf abgelaufen oder verändert; erneut entwerfen"
                ) from None
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(text(f"SELECT pg_advisory_xact_lock({ARTIFACT_STORAGE})"))
        active = (
            db.scalar(
                select(func.count())
                .select_from(ArtifactRevision)
                .where(ArtifactRevision.status.in_(["queued", "rendering"]))
            )
            or 0
        )
        total = db.scalar(select(func.count()).select_from(ArtifactRevision)) or 0
        if active >= 4 or total >= 1000:
            raise HTTPException(429, "Dateigrenze erreicht: vier aktive Aufträge, 1000 Versionen")
        try:
            used = storage_bytes(cfg)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if used + (active + 1) * 320 * 1024 * 1024 > 2 * 1024 * 1024 * 1024:
            raise HTTPException(413, "Dateispeicher voll: 2 GiB einschließlich Auftragsreserve")
        if artifact_id:
            artifact = db.scalar(
                select(Artifact).where(Artifact.id == artifact_id).with_for_update()
            )
            if not artifact or artifact.project_id != project_id:
                raise HTTPException(404, "Artefakt nicht gefunden")
            if body.expected_revision != artifact.revision:
                raise HTTPException(409, "Artefakt wurde inzwischen geändert")
            previous = db.get(ArtifactRevision, (artifact.id, artifact.revision))
            if previous and not body.chat_source:
                chat_metadata = previous.chat_metadata
            artifact.revision += 1
        else:
            if body.expected_revision is not None:
                raise HTTPException(422, "Erste Dateiversion benötigt keine alte Revision")
            artifact = Artifact(project_id=project_id)
            db.add(artifact)
            db.flush()
        row = ArtifactRevision(
            artifact_id=artifact.id,
            revision=artifact.revision,
            request_key=str(body.request_id),
            spec=document,
            spec_sha256=digest(document),
            draft_metadata=metadata,
            chat_metadata=chat_metadata,
        )
        db.add(row)
        db.flush()
        dispatch(db, row)
        return row, True

    async def save(
        project_id: str, artifact_id: str | None, body: CreateArtifact
    ) -> dict[str, Any]:
        enabled()

        def transaction() -> tuple[dict[str, Any], bool]:
            with factory() as db:
                try:
                    row, created = create_row(db, project_id, artifact_id, body)
                    db.commit()
                    result = info(row)
                except IntegrityError as exc:
                    db.rollback()
                    raise HTTPException(
                        409, "Dateianfrage inzwischen gespeichert; Status prüfen"
                    ) from exc
            return result, created

        result, created = await asyncio.to_thread(transaction)
        if created and cfg.database_url.startswith("sqlite"):
            # Development only. Production always dispatches in its PG transaction.
            asyncio.create_task(
                execute_artifact(factory, cfg, result["artifact_id"], result["revision"])
            )
        return result

    @app.get("/api/artifact-status")
    def artifact_status(auth: Auth) -> dict[str, Any]:
        try:
            roots(cfg)
            return {"configured": True, "label": "LOCAL_ONLY"}
        except ValueError:
            return {"configured": False, "label": "LOCAL_ONLY"}

    @app.post("/api/projects/{project_id}/artifacts")
    async def create(project_id: str, body: CreateArtifact, auth: Auth) -> dict[str, Any]:
        return await save(project_id, None, body)

    @app.post("/api/projects/{project_id}/artifacts/{artifact_id}/versions")
    async def version(
        project_id: str, artifact_id: str, body: CreateArtifact, auth: Auth
    ) -> dict[str, Any]:
        return await save(project_id, artifact_id, body)

    @app.get("/api/projects/{project_id}/artifacts")
    def listing(project_id: str, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            if not db.scalar(select(Project).where(Project.id == project_id).with_for_update()):
                raise HTTPException(404, "Projekt nicht gefunden")
            rows = db.scalars(
                select(ArtifactRevision)
                .join(Artifact)
                .where(Artifact.project_id == project_id)
                .order_by(ArtifactRevision.created.desc())
                .limit(200)
                .with_for_update()
            ).all()
            try:
                roots(cfg)
                configured = True
            except ValueError:
                configured = False
            if configured:
                for row in rows:
                    reconcile(db, cfg, row)
                db.commit()
            return [info(row) for row in rows]

    @app.post("/api/projects/{project_id}/artifacts/{artifact_id}/versions/{revision}/accept")
    def accept(
        project_id: str, artifact_id: str, revision: int, body: AcceptArtifact, auth: Auth
    ) -> dict[str, Any]:
        enabled()
        with factory() as db:
            row = row_for(db, project_id, artifact_id, revision)
            reconcile(db, cfg, row)
            if row.status not in {"needs_review", "published"} or not row.manifest:
                raise HTTPException(409, "Dateiversion ist noch nicht vollständig prüfbar")
            try:
                manifest = checked_manifest(cfg, row, row.manifest)
                bind_sources(db, cfg, project_id, spec_for(row))
            except (ValueError, OSError) as exc:
                raise HTTPException(409, "Dateiversion oder Quellen wurden verändert") from exc
            if (
                not body.reviewed_all_pages
                or body.spec_sha256 != row.spec_sha256
                or body.output_sha256 != manifest.sha256
            ):
                raise HTTPException(409, "Alle Vorschauseiten der genauen Version prüfen")
            if row.status != "published":
                row.status, row.accepted = "published", time.time()
            db.commit()
            return info(row)

    @app.post("/api/projects/{project_id}/artifacts/{artifact_id}/versions/{revision}/cancel")
    def cancel(project_id: str, artifact_id: str, revision: int, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            row = row_for(db, project_id, artifact_id, revision)
            if row.status == "published":
                raise HTTPException(409, "Freigegebene Dateiversion bleibt erhalten")
            row.status = "cancelled"
            db.commit()
            return info(row)

    @app.get(
        "/api/projects/{project_id}/artifacts/{artifact_id}/versions/{revision}/preview/{page}"
    )
    def preview(
        project_id: str, artifact_id: str, revision: int, page: int, auth: Auth
    ) -> FileResponse:
        enabled()
        with factory() as db:
            row = row_for(db, project_id, artifact_id, revision)
            if row.status not in {"needs_review", "published"} or not row.manifest:
                raise HTTPException(409, "Vorschau ist noch nicht bereit")
            try:
                manifest = checked_manifest(cfg, row, row.manifest)
                if not 1 <= page <= len(manifest.previews):
                    raise HTTPException(404, "Vorschauseite fehlt")
                file = manifest.previews[page - 1]
                path = output_file(cfg, row, file.filename, file.sha256)
            except (ValueError, OSError) as exc:
                raise HTTPException(409, "Vorschau wurde verändert") from exc
            return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/projects/{project_id}/artifacts/{artifact_id}/versions/{revision}/download")
    def download(
        project_id: str, artifact_id: str, revision: int, auth: Auth, pdf: bool = False
    ) -> FileResponse:
        enabled()
        with factory() as db:
            row = row_for(db, project_id, artifact_id, revision)
            if row.status != "published" or not row.manifest:
                raise HTTPException(409, "Vorschau erst prüfen und Dateiversion freigeben")
            try:
                manifest = checked_manifest(cfg, row, row.manifest)
                if pdf and not manifest.pdf_export:
                    raise HTTPException(404, "Für diese Version wurde kein PDF-Export erstellt")
                file = manifest.pdf_export if pdf else manifest
                assert file is not None
                path = output_file(cfg, row, file.filename, file.sha256)
            except (ValueError, OSError) as exc:
                raise HTTPException(409, "Dateiversion wurde verändert") from exc
            return FileResponse(
                path,
                filename="artifact.pdf" if pdf else manifest.filename,
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )
