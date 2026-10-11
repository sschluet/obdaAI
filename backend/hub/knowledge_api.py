"""Authenticated M2 endpoints; every content operation requires an explicit scope."""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from hub.auth import require_session
from hub.config import Settings
from hub.db import LoginSession, Project, Source
from hub.db_locks import ownership_lock
from hub.deletion import DeletionInput, permanently_delete, preview
from hub.extract import EXTENSIONS, MAX_BYTES
from hub.knowledge import calculate, extract_source, original, retrieve, store
from hub.project_icons import DEFAULT_PROJECT_ICON, PROJECT_ICONS, ProjectIcon

Auth = Annotated[LoginSession, Depends(require_session)]


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=8000)
    instructions: str = Field(default="", max_length=8000)
    revision: int | None = None
    archived: bool = False
    icon: ProjectIcon | None = None


class WebsiteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=2048)
    public_url_approved: bool = False
    request_id: UUID


def project_info(p: Project) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "icon": p.icon,
        "description": p.description,
        "instructions": p.instructions,
        "label": p.label,
        "revision": p.revision,
        "archived": p.archived,
        "kind": p.kind,
    }


def source_info(s: Source) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "sha256": s.sha256,
        "size": s.size,
        "status": s.status,
        "error": s.error,
        "label": s.label,
        "revision": s.revision,
        "origin_url": s.origin_url,
    }


def install_knowledge_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/project-icons")
    def project_icons(auth: Auth) -> list[str]:
        return list(PROJECT_ICONS)

    @app.get("/api/projects")
    def projects(auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            return [
                project_info(p)
                for p in db.scalars(
                    select(Project).where(Project.kind == "project").order_by(Project.name)
                )
            ]

    @app.get("/api/projects/{project_id}")
    def detail(project_id: str, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            p = db.get(Project, project_id)
            if not p:
                raise HTTPException(404, "Projektraum nicht gefunden")
            return project_info(p)

    @app.post("/api/projects")
    def create(body: ProjectInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            project = Project(
                name=body.name,
                description=body.description,
                instructions=body.instructions,
                icon=body.icon or DEFAULT_PROJECT_ICON,
            )
            db.add(project)
            db.commit()
            return project_info(project)

    @app.patch("/api/projects/{project_id}")
    def edit(project_id: str, body: ProjectInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            if not project:
                raise HTTPException(404, "Projekt nicht gefunden")
            if body.revision != project.revision:
                raise HTTPException(409, "Projekt inzwischen geändert")
            project.name, project.description = body.name, body.description
            project.instructions, project.archived = body.instructions, body.archived
            if body.icon is not None:
                project.icon = body.icon
            project.revision += 1
            db.commit()
            return project_info(project)

    @app.get("/api/projects/{project_id}/deletion")
    def deletion_preview(project_id: str, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return preview(db, "project", project_id, cfg)

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str, body: DeletionInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            result = permanently_delete(db, cfg, "project", project_id, body)
        if cfg.database_url.startswith("sqlite") and result["cleanup_id"]:
            from hub.deletion_cleanup import inline_cleanup

            inline_cleanup(factory, cfg)
        return result

    @app.get("/api/projects/{project_id}/sources")
    def sources(project_id: str, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            if not db.get(Project, project_id):
                raise HTTPException(404, "Projekt nicht gefunden")
            return [
                source_info(s)
                for s in db.scalars(
                    select(Source)
                    .where(Source.project_id == project_id)
                    .order_by(Source.created.desc())
                )
            ]

    @app.post("/api/projects/{project_id}/sources")
    async def upload(project_id: str, request: Request, auth: Auth) -> dict[str, Any]:
        # Raw bounded streaming avoids unbounded multipart spooling in the API.
        name = request.headers.get("X-File-Name", "")
        from urllib.parse import unquote

        name = unquote(name)
        if (
            not name
            or len(name) > 240
            or Path(name).name != name
            or "\\" in name
            or any(ord(c) < 32 for c in name)
            or Path(name).suffix.lower() not in EXTENSIONS
        ):
            raise HTTPException(422, "Nicht unterstützter Dateiname oder Dateityp")
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, "Maximal 40 MiB pro Datei")
            content.extend(chunk)
        if not content:
            raise HTTPException(422, "Leere Datei")
        with factory() as db:
            ownership_lock(db)
            project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            if not project or project.archived:
                raise HTTPException(404, "Aktives Projekt nicht gefunden")
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(791103042)"))
            total = db.scalar(select(func.sum(Source.size))) or 0
            if total + len(content) > 2 * 1024 * 1024 * 1024:
                raise HTTPException(413, "Gesamtgrenze: 2 GiB Originaldateien")
            count, used = db.execute(
                select(func.count(Source.id), func.sum(Source.size)).where(
                    Source.project_id == project_id
                )
            ).one()
            if count >= 100 or (used or 0) + len(content) > 200 * 1024 * 1024:
                raise HTTPException(413, "Projektgrenze: 100 Dateien / 200 MiB")
            source = Source(
                project_id=project_id,
                name=name,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
            db.add(source)
            db.flush()
            store(cfg, source, bytes(content))
            if not cfg.database_url.startswith("sqlite"):
                from hub.jobs import enqueue_source

                enqueue_source(db, cfg, source.id)
            db.commit()
            info = source_info(source)
        if cfg.database_url.startswith("sqlite"):
            task = asyncio.create_task(extract_source(factory, cfg, source.id))
            app.state.tasks.add(task)
            task.add_done_callback(app.state.tasks.discard)
        return info

    @app.post("/api/projects/{project_id}/websites")
    async def website(project_id: str, body: WebsiteInput, auth: Auth) -> dict[str, Any]:
        from urllib.parse import urlsplit

        import httpx

        from hub.websearch import fetch_page

        if not body.public_url_approved:
            raise HTTPException(403, "Die konkrete öffentliche Webseite zuerst zum Abruf auswählen")
        with factory() as db:
            ownership_lock(db)
            p = db.get(Project, project_id)
            if not p or p.archived or p.kind != "project":
                raise HTTPException(404, "Aktiver Projektraum nicht gefunden")
            old = db.scalar(select(Source).where(Source.web_request_id == str(body.request_id)))
            if old:
                if old.project_id != project_id or old.origin_url != body.url:
                    raise HTTPException(409, "Webseitenauftrag anders verwendet")
                return source_info(old)
        try:
            from hub.source_network import request_network

            await request_network(factory, cfg, "website", {"url": body.url})
            content = await fetch_page(cfg, body.url, True, user_selected=True)
            if not content.strip():
                raise ValueError("Empty page")
        except (ValueError, OSError, httpx.HTTPError):
            raise HTTPException(
                422,
                "Öffentliche HTTPS-Seite nicht abrufbar. "
                "Private Adressen, Anmeldung und Weiterleitungen werden nicht verwendet",
            ) from None
        payload = (
            "Öffentliche Webseite: " + body.url + "\nAbruf: " + str(time.time()) + "\n\n" + content
        ).encode()
        with factory() as db:
            ownership_lock(db)
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(791103042)"))
            p = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            if not p or p.archived:
                raise HTTPException(409, "Projektraum inzwischen archiviert")
            old = db.scalar(select(Source).where(Source.web_request_id == str(body.request_id)))
            if old:
                if old.project_id != project_id or old.origin_url != body.url:
                    raise HTTPException(409, "Webseitenauftrag anders verwendet")
                return source_info(old)
            count, used = db.execute(
                select(func.count(Source.id), func.sum(Source.size)).where(
                    Source.project_id == project_id
                )
            ).one()
            if (
                count >= 100
                or (used or 0) + len(payload) > 200 * 1024 * 1024
                or (db.scalar(select(func.sum(Source.size))) or 0) + len(payload)
                > 2 * 1024 * 1024 * 1024
            ):
                raise HTTPException(413, "Quellen-Speichergrenze erreicht")
            name = "Webseite_" + (urlsplit(body.url).hostname or "quelle")[:150] + ".txt"
            source = Source(
                project_id=project_id,
                name=name,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                origin_url=body.url,
                web_request_id=str(body.request_id),
            )
            db.add(source)
            db.flush()
            store(cfg, source, payload)
            if not cfg.database_url.startswith("sqlite"):
                from hub.jobs import enqueue_source

                enqueue_source(db, cfg, source.id)
            db.commit()
            info = source_info(source)
        if cfg.database_url.startswith("sqlite"):
            job = asyncio.create_task(extract_source(factory, cfg, source.id))
            app.state.tasks.add(job)
            job.add_done_callback(app.state.tasks.discard)
        return info

    @app.get("/api/projects/{project_id}/sources/{source_id}/original")
    def download(project_id: str, source_id: str, auth: Auth) -> FileResponse:
        with factory() as db:
            source = db.get(Source, source_id)
            if not source or source.project_id != project_id:
                raise HTTPException(404, "Quelle nicht gefunden")
            try:
                return FileResponse(
                    original(cfg, source),
                    filename=source.name,
                    media_type="application/octet-stream",
                )
            except ValueError as error:
                raise HTTPException(409, str(error)) from None

    @app.get("/api/projects/{project_id}/search")
    def search(project_id: str, auth: Auth, q: str = "") -> list[dict[str, Any]]:
        if len(q) > 500:
            raise HTTPException(422, "Suchtext zu lang")
        with factory() as db:
            if not db.get(Project, project_id):
                raise HTTPException(404, "Projekt nicht gefunden")
            return retrieve(db, project_id, q)

    @app.get("/api/projects/{project_id}/sources/{source_id}/sum")
    def sum_column(project_id: str, source_id: str, auth: Auth, column: int = 0) -> dict[str, Any]:
        if not 0 <= column < 200:
            raise HTTPException(422, "Ungültige Spalte")
        with factory() as db:
            try:
                return calculate(db, project_id, source_id, column)
            except ValueError as error:
                raise HTTPException(404, str(error)) from None

    @app.post("/api/projects/{project_id}/sources/{source_id}/retry")
    async def retry(
        project_id: str, source_id: str, request: Request, auth: Auth
    ) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            source = db.scalar(select(Source).where(Source.id == source_id).with_for_update())
            if not source or source.project_id != project_id:
                raise HTTPException(404, "Quelle im Projekt nicht gefunden")
            project = db.get(Project, project_id)
            if not project or project.archived:
                raise HTTPException(409, "Projekt archiviert")
            if source.status in {"queued", "extracting"}:
                raise HTTPException(409, "Extraktion bereits aktiv")
            if source.revision >= 1000:
                raise HTTPException(409, "Revisionslimit erreicht")
            source.revision += 1
            source.status, source.error = "queued", ""
            if not cfg.database_url.startswith("sqlite"):
                from hub.jobs import enqueue_source

                enqueue_source(db, cfg, source_id)
            db.commit()
            info = source_info(source)
        if cfg.database_url.startswith("sqlite"):
            task = asyncio.create_task(extract_source(factory, cfg, source_id))
            app.state.tasks.add(task)
            task.add_done_callback(app.state.tasks.discard)
        return info
