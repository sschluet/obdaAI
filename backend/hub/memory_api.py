"""Explicit human memory writes; source text never invokes this API."""

import time
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from hub.config import Settings
from hub.db import Memory, MemoryRevision, Project
from hub.db_locks import ownership_lock
from hub.knowledge_api import Auth
from hub.memory import (
    digest,
    read_note,
    reconcile,
    revision,
    serialize,
    validate_mount,
    vault_path,
    write,
)


class MemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=200000)
    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    revision: int = Field(default=1, ge=1)
    resolve_vault_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    storage: Literal["vault", "app"] = "vault"
    category: Literal["knowledge", "personal", "project", "conversation", "preference"] = "personal"
    fact_type: Literal["fact", "plan", "hypothesis", "decision"] = "fact"
    subject: str = Field(default="", max_length=120)
    predicate: str = Field(default="", max_length=120)
    sensitivity: Literal["public", "private", "sensitive"] = "private"
    cloud_providers: list[Literal["openrouter", "openai", "anthropic"]] = Field(
        default_factory=list
    )
    valid_from: float | None = None
    valid_until: float | None = None


def info(row: Memory) -> dict[str, Any]:
    if row.storage == "app":
        from hub.memory_service import memory_info

        return memory_info(row)
    return {
        "id": row.id,
        "origin": row.origin,
        "path": row.path,
        "project_id": row.project_id,
        "label": row.label,
        "revision": row.revision,
        "sha256": row.sha256,
        "content": row.content,
        "conflict": row.conflict,
        "deleted": row.deleted,
        "writable": row.writable,
        "updated": row.updated,
        "storage": row.storage,
        "category": row.category,
        "status": row.status,
    }


def install_memory_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    def root() -> Path:
        if not cfg.vault_dir:
            raise HTTPException(409, "Vault noch nicht angebunden; kein Abgleich durchgeführt")
        path = Path(cfg.vault_dir)
        try:
            validate_mount(path, cfg.vault_fs_type)
        except (ValueError, OSError) as error:
            raise HTTPException(409, str(error)) from None
        return path

    @app.get("/api/memories")
    def listing(
        auth: Auth, project_id: str | None = None, q: str = "", deleted: bool = False,
        category: str | None = None, status: str | None = None, all_projects: bool = False,
    ) -> list[dict[str, Any]]:
        if len(q) > 500:
            raise HTTPException(422, "Suchtext zu lang")
        with factory() as db:
            statement = select(Memory).where(Memory.owner_id == "owner", Memory.deleted == deleted)
            if not all_projects:
                statement = statement.where(Memory.project_id == project_id)
            if category:
                statement = statement.where(Memory.category == category)
            if status == "expired":
                statement = statement.where(
                    Memory.status == "active", Memory.valid_until <= time.time()
                )
            elif status == "active":
                statement = statement.where(
                    Memory.status == "active",
                    or_(Memory.valid_until.is_(None), Memory.valid_until > time.time()),
                )
            elif status:
                statement = statement.where(Memory.status == status)
            if q:
                statement = statement.where(Memory.content.icontains(q, autoescape=True))
            return [
                info(m) for m in db.scalars(statement.order_by(Memory.updated.desc()).limit(100))
            ]

    @app.get("/api/memories/{memory_id}")
    def current(memory_id: str, auth: Auth, project_id: str | None = None) -> dict[str, Any]:
        with factory() as db:
            row = db.get(Memory, memory_id)
            if not row or row.deleted or row.project_id != project_id:
                raise HTTPException(404, "Aktives Memory im Scope nicht gefunden")
            return info(row)

    @app.post("/api/memories/sync")
    def sync(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            try:
                result = reconcile(
                    db,
                    root(),
                    allow_memory_writes=cfg.vault_writable,
                    expected_fs=cfg.vault_fs_type,
                )
                db.commit()
                return result
            except (ValueError, OSError):
                db.rollback()
                raise HTTPException(
                    409, "Vault-Abgleich fehlgeschlagen; Index unverändert"
                ) from None

    @app.post("/api/memories")
    def create(body: MemoryInput, auth: Auth) -> dict[str, Any]:
        if body.storage == "app":
            from hub.memory_service import create_app_memory

            with factory() as db:
                try:
                    row = create_app_memory(
                        db, identifier=body.id, content=body.content, title=body.title,
                        category=body.category, fact_type=body.fact_type, subject=body.subject,
                        predicate=body.predicate, sensitivity=body.sensitivity,
                        cloud_providers=[str(p) for p in body.cloud_providers],
                        project_id=body.project_id,
                        valid_from=body.valid_from, valid_until=body.valid_until,
                    )
                    db.commit()
                    return info(row)
                except (ValueError, PermissionError) as error:
                    raise HTTPException(409, str(error)) from None
        if not cfg.vault_writable:
            raise HTTPException(409, "Memory-Schreibbereich noch nicht freigegeben")
        target = root()
        with factory() as db:
            serialize(db)
            ownership_lock(db)
            previous = db.get(Memory, body.id)
            text = "# " + body.title + "\n\n" + body.content
            if previous:
                if previous.conflict.startswith("pending:"):
                    raise HTTPException(409, "Memory-Schreibvorgang läuft; zuerst synchronisieren")
                if previous.content != text or previous.project_id != body.project_id:
                    raise HTTPException(409, "Memory-ID bereits anders verwendet")
                return info(previous)
            if body.project_id and not db.get(Project, body.project_id):
                raise HTTPException(404, "Projekt nicht gefunden")
            row = Memory(
                id=body.id,
                path="AI/Memory/" + body.id + ".md",
                project_id=body.project_id,
                origin="app",
                writable=True,
                content="",
                base_content="",
                sha256=digest(""),
            )
            db.add(row)
            db.flush()
            try:
                write(db, target, row, text, 1)
            except (ValueError, OSError, PermissionError) as error:
                raise HTTPException(409, str(error)) from None
            return info(row)

    @app.patch("/api/memories/{memory_id}")
    def edit(memory_id: str, body: MemoryInput, auth: Auth) -> dict[str, Any]:
        if body.storage == "app":
            from hub.memory_service import edit_app_memory

            if body.id != memory_id:
                raise HTTPException(409, "Memory-ID ungültig")
            with factory() as db:
                row = db.get(Memory, memory_id)
                if not row or row.storage != "app" or row.owner_id != "owner":
                    raise HTTPException(404, "Erinnerung nicht gefunden")
                try:
                    edit_app_memory(
                        db, row, expected_revision=body.revision, content=body.content,
                        title=body.title, category=body.category, fact_type=body.fact_type,
                        subject=body.subject, predicate=body.predicate,
                        sensitivity=body.sensitivity,
                        cloud_providers=[str(p) for p in body.cloud_providers],
                        project_id=body.project_id, valid_from=body.valid_from,
                        valid_until=body.valid_until,
                    )
                    db.commit()
                    return info(row)
                except (ValueError, PermissionError) as error:
                    raise HTTPException(409, str(error)) from None
        if not cfg.vault_writable or body.id != memory_id:
            raise HTTPException(409, "Schreibfreigabe oder Memory-ID ungültig")
        with factory() as db:
            serialize(db)
            ownership_lock(db)
            row = db.scalar(select(Memory).where(Memory.id == memory_id))
            if not row or row.project_id != body.project_id:
                raise HTTPException(404, "Memory im Scope nicht gefunden")
            if row.project_id and db.get(Project, row.project_id) is None:
                raise HTTPException(
                    409, "Projekt wurde gelöscht; historisches Memory bleibt erhalten"
                )
            if row.conflict.startswith("pending:"):
                raise HTTPException(409, "Memory-Schreibvorgang läuft; zuerst synchronisieren")
            if body.resolve_vault_sha256:
                from hub.memory import decode

                try:
                    _, actual = decode(read_note(root(), row.path))
                except (ValueError, OSError) as error:
                    raise HTTPException(409, "Vault-Datei nicht sicher lesbar") from error
                if digest(actual) != body.resolve_vault_sha256 or body.revision != row.revision:
                    raise HTTPException(409, "Verglichene Vault-Version inzwischen geändert")
                # Explicit comparison approval is bound to the actual file digest.
                row.sha256, row.base_content = digest(actual), actual
                row.conflict = ""
            try:
                write(db, root(), row, "# " + body.title + "\n\n" + body.content, body.revision)
            except (ValueError, OSError, PermissionError) as error:
                raise HTTPException(409, str(error)) from None
            return info(row)

    @app.get("/api/memories/{memory_id}/versions")
    def versions(memory_id: str, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            if not db.get(Memory, memory_id):
                raise HTTPException(404, "Memory nicht gefunden")
            return [
                {
                    "revision": r.revision,
                    "content": r.content,
                    "sha256": r.sha256,
                    "created": r.created,
                }
                for r in db.scalars(
                    select(MemoryRevision)
                    .where(MemoryRevision.memory_id == memory_id)
                    .order_by(MemoryRevision.revision.desc())
                )
            ]

    @app.delete("/api/memories/{memory_id}")
    def remove(memory_id: str, auth: Auth, expected_revision: int) -> dict[str, bool]:
        with factory() as db:
            row = db.get(Memory, memory_id)
            if row is not None and row.storage == "app":
                from hub.memory_service import forget_memory

                try:
                    forget_memory(db, row, expected_revision=expected_revision)
                    db.commit()
                    return {"ok": True}
                except (ValueError, PermissionError) as error:
                    raise HTTPException(409, str(error)) from None
        if not cfg.vault_writable:
            raise HTTPException(409, "Memory-Schreibbereich nicht freigegeben")
        with factory() as db:
            serialize(db)
            row = db.scalar(select(Memory).where(Memory.id == memory_id))
            if not row or not row.writable or not row.path.startswith("AI/Memory/"):
                raise HTTPException(404, "Schreibbares Memory nicht gefunden")
            if row.revision != expected_revision or row.conflict:
                raise HTTPException(409, "Memory geändert; zuerst synchronisieren")
            path = vault_path(root(), row.path)
            if path.exists():
                from hub.memory import decode

                _, actual = decode(path.read_text(encoding="utf-8"))
                if digest(actual) != row.sha256:
                    raise HTTPException(409, "Vault wurde verändert; Löschung abgebrochen")
                # Recoverable archive outside live Markdown indexing; preserved original.
                archive = vault_path(root(), "AI/Memory/.obdaai-trash/" + row.id)
                archive.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
                path.replace(archive)
            revision(db, row)
            row.deleted, row.revision = True, row.revision + 1
            db.commit()
            return {"ok": True}
