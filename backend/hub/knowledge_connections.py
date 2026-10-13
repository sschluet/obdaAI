"""Separate configurable RAG sources with encrypted credentials and local snapshots."""

import asyncio
import hashlib
import json
import time
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput, encode
from hub.config import Settings
from hub.db import KnowledgeConnection, KnowledgeDocument, Memory, Project, Source
from hub.extract import MAX_BYTES
from hub.knowledge import extract_source, store
from hub.knowledge_api import Auth
from hub.knowledge_clients import ConnectionInput, documents
from hub.memory import validate_mount
from hub.provider_settings import decrypt, encrypt
from hub.task_api import lock


class ConnectionControl(StrictInput):
    revision: int = Field(ge=1)
    enabled: bool


def info(db: Session, row: KnowledgeConnection) -> dict[str, Any]:
    ready = (
        db.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.project_id == row.project_id, Source.status == "ready")
        )
        or 0
    )
    pending = (
        db.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.project_id == row.project_id, Source.status.in_(["queued", "extracting"]))
        )
        or 0
    )
    failed = (
        db.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.project_id == row.project_id, Source.status == "failed")
        )
        or 0
    )
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "address": row.address,
        "project_id": row.project_id,
        "revision": row.revision,
        "status": "processing"
        if pending
        else ("partial" if failed and row.status == "ready" else row.status),
        "enabled": row.enabled,
        "indexed": ready,
        "pending": pending,
        "failed": failed,
        "last_indexed": row.last_indexed,
        "error": row.error,
        "config": json.loads(row.config),
        "secret_set": bool(row.encrypted_secret),
        "chat_ready": row.enabled and ready > 0 and row.status in {"ready", "partial"},
    }


def check_chat_source(db: Session, project_id: str) -> None:
    row = db.scalar(select(KnowledgeConnection).where(KnowledgeConnection.project_id == project_id))
    if (
        not row
        or not row.enabled
        or row.status not in {"ready", "partial"}
        or not (
            db.scalar(
                select(func.count())
                .select_from(Source)
                .where(Source.project_id == project_id, Source.status == "ready")
            )
            or 0
        )
    ):
        raise ValueError("Wissensquelle ist deaktiviert oder noch nicht vollständig verbunden")


def credentials(cfg: Settings, row: KnowledgeConnection) -> str:
    return decrypt(cfg, "knowledge:" + row.id, row.encrypted_secret) if row.encrypted_secret else ""


async def index_connection(
    factory: sessionmaker[Session], cfg: Settings, connection_id: str, revision: int
) -> None:
    try:
        with factory() as db:
            row = db.get(KnowledgeConnection, connection_id)
            if not row or not row.enabled or row.revision != revision or row.status != "indexing":
                return
            body = ConnectionInput.model_validate(json.loads(row.config))
            password = credentials(cfg, row)
    except Exception:
        with factory() as db:
            row = db.get(KnowledgeConnection, connection_id)
            if row and row.revision == revision and row.status == "indexing":
                row.status = "failed"
                row.error = "Verschlüsselte Zugangsdaten nicht verfügbar; Ablage und Quelle prüfen."
                db.commit()
        return
    iterator = documents(body, password)
    imported, seen, total = [], set(), 0
    try:
        from hub.source_network import request_network

        await request_network(factory, cfg, body.kind, body.public())
        sentinel = object()
        while True:
            document = await asyncio.to_thread(next, iterator, sentinel)
            if document is sentinel:
                break
            assert hasattr(document, "content") and hasattr(document, "path")
            content, path = document.content, document.path
            sha = hashlib.sha256(content).hexdigest()
            if not content or len(content) > MAX_BYTES or total + len(content) > 200 * 1024 * 1024:
                raise ValueError("Knowledge snapshot limit")
            total += len(content)
            seen.add(path)
            with factory() as db:
                lock(db)
                row = db.get(KnowledgeConnection, connection_id)
                if (
                    not row
                    or not row.enabled
                    or row.revision != revision
                    or row.status != "indexing"
                ):
                    return
                old = db.scalar(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.connection_id == row.id, KnowledgeDocument.path == path
                    )
                )
                if old and old.fingerprint == sha:
                    previous = db.get(Source, old.source_id)
                    if previous and previous.status in {"ready", "queued", "extracting"}:
                        continue
                if (db.scalar(select(func.sum(Source.size))) or 0) + len(
                    content
                ) > 2 * 1024 * 1024 * 1024:
                    raise ValueError("Global snapshot limit")
                count = (
                    db.scalar(
                        select(func.count())
                        .select_from(Source)
                        .where(Source.project_id == row.project_id)
                    )
                    or 0
                )
                if count >= 1000:
                    raise ValueError("Knowledge version limit")
                name = PurePosixPath(path).name
                source = Source(project_id=row.project_id, name=name, size=len(content), sha256=sha)
                db.add(source)
                db.flush()
                store(cfg, source, content)
                if old:
                    previous = db.get(Source, old.source_id)
                    if previous:
                        previous.status = "superseded"
                    old.source_id, old.fingerprint = source.id, sha
                else:
                    db.add(
                        KnowledgeDocument(
                            connection_id=row.id, path=path, fingerprint=sha, source_id=source.id
                        )
                    )
                if not cfg.database_url.startswith("sqlite"):
                    from hub.jobs import enqueue_source

                    enqueue_source(db, cfg, source.id)
                imported.append(source.id)
                db.commit()
        with factory() as db:
            lock(db)
            row = db.get(KnowledgeConnection, connection_id)
            if row and row.enabled and row.revision == revision and row.status == "indexing":
                row.status = (
                    "partial" if len(seen) >= body.max_files and body.kind != "sql" else "ready"
                )
                row.indexed = len(seen)
                row.last_indexed = time.time()
                row.error = (
                    "Dokumentgrenze erreicht; einen engeren Ordner wählen oder die Grenze erhöhen."
                    if row.status == "partial"
                    else ""
                )
                db.commit()
    except Exception:
        with factory() as db:
            row = db.get(KnowledgeConnection, connection_id)
            if row and row.revision == revision and row.status == "indexing":
                row.status = "failed"
                row.error = (
                    "Indexierung nicht abgeschlossen. Server, Zugriff und Speichergrenzen prüfen. "
                    "Vorhandene Momentaufnahmen bleiben erhalten."
                )
                db.commit()
    finally:
        await asyncio.to_thread(iterator.close)
        if cfg.database_url.startswith("sqlite"):
            for source_id in imported:
                await extract_source(factory, cfg, source_id)


def install_knowledge_connections(
    app: FastAPI, cfg: Settings, factory: sessionmaker[Session]
) -> None:
    @app.get("/api/knowledge-sources")
    def listing(auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            mounted = False
            if cfg.vault_dir:
                try:
                    validate_mount(Path(cfg.vault_dir), cfg.vault_fs_type)
                    mounted = True
                except (ValueError, OSError):
                    pass
            count = (
                db.scalar(
                    select(func.count())
                    .select_from(Memory)
                    .where(
                        Memory.deleted.is_(False),
                        Memory.project_id.is_(None),
                        Memory.conflict == "",
                    )
                )
                or 0
            )
            return [
                {
                    "id": "vault",
                    "name": "Obsidian · vorhandener Vault",
                    "kind": "vault",
                    "enabled": mounted,
                    "status": "ready" if mounted else "needs_setup",
                    "indexed": count,
                    "pending": 0,
                    "chat_ready": mounted and count > 0,
                    "error": "",
                    "builtin": True,
                }
            ] + [
                info(db, r)
                for r in db.scalars(select(KnowledgeConnection).order_by(KnowledgeConnection.name))
            ]

    @app.post("/api/knowledge-sources")
    def create(body: ConnectionInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            p = Project(name=body.name, kind="knowledge")
            db.add(p)
            db.flush()
            row = KnowledgeConnection(
                name=body.name,
                kind=body.kind,
                address=body.server,
                project_id=p.id,
                config=encode(body.public()),
            )
            db.add(row)
            db.flush()
            if body.password:
                try:
                    row.encrypted_secret = encrypt(cfg, "knowledge:" + row.id, body.password)
                except (ValueError, OSError):
                    raise HTTPException(
                        503, "Verschlüsselte Zugangsdatenablage nicht eingerichtet"
                    ) from None
            db.commit()
            return info(db, row)

    @app.put("/api/knowledge-sources/{connection_id}")
    def edit(connection_id: str, body: ConnectionInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            row = db.get(KnowledgeConnection, connection_id)
            if not row or row.revision != body.revision:
                raise HTTPException(409, "Wissensquelle inzwischen geändert")
            if row.status == "indexing":
                raise HTTPException(409, "Laufende Indexierung zuerst beenden lassen")
            previous = json.loads(row.config)
            identity = [
                "server",
                "kind",
                "share",
                "folder",
                "username",
                "database",
                "port",
                "schema_name",
                "table",
                "uid",
                "gid",
            ]
            if (
                row.encrypted_secret
                and body.password is None
                and any(previous.get(k) != body.public().get(k) for k in identity)
            ):
                raise HTTPException(
                    422, "Bei geändertem Server/Zugang die Zugangsdaten erneut angeben"
                )
            if body.password is not None:
                row.encrypted_secret = (
                    encrypt(cfg, "knowledge:" + row.id, body.password) if body.password else ""
                )
            if any(previous.get(k) != body.public().get(k) for k in identity):
                for source in db.scalars(
                    select(Source).where(
                        Source.project_id == row.project_id, Source.status == "ready"
                    )
                ):
                    source.status = "superseded"
            row.name, row.kind, row.address, row.config = (
                body.name,
                body.kind,
                body.server,
                encode(body.public()),
            )
            project = db.get(Project, row.project_id)
            if project and project.name != body.name:
                project.name = body.name
                project.revision += 1
            row.revision += 1
            row.enabled = False
            row.status = "needs_setup"
            row.error = ""
            db.commit()
            return info(db, row)

    @app.post("/api/knowledge-sources/{connection_id}/test")
    async def test(connection_id: str, body: ConnectionControl, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            row = db.get(KnowledgeConnection, connection_id)
            if not row or row.revision != body.revision:
                raise HTTPException(409, "Wissensquelle inzwischen geändert")
            config = ConnectionInput.model_validate_json(row.config)
            password = credentials(cfg, row)

        def probe() -> None:
            iterator = documents(config, password, probe=True)
            try:
                next(iterator, None)
            finally:
                iterator.close()

        try:
            from hub.source_network import request_network

            await request_network(factory, cfg, config.kind, config.public())
            await asyncio.to_thread(probe)
        except Exception:
            raise HTTPException(
                409,
                "Verbindung nicht bestätigt. "
                "Server, Berechtigungen und verschlüsselten Zugriff prüfen.",
            ) from None
        with factory() as db:
            current_row = db.get(KnowledgeConnection, connection_id)
            if not current_row or current_row.revision != body.revision:
                raise HTTPException(409, "Wissensquelle während des Tests geändert")
        return {
            "ok": True,
            "message": "Verbindung und lesender Zugriff bestätigt. "
            "Jetzt kannst du die Quelle indexieren.",
        }

    @app.post("/api/knowledge-sources/{connection_id}/index")
    async def index(connection_id: str, body: ConnectionControl, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            row = db.get(KnowledgeConnection, connection_id)
            if not row or row.revision != body.revision:
                raise HTTPException(409, "Wissensquelle inzwischen geändert")
            if row.status == "indexing":
                return info(db, row)
            row.revision += 1
            row.enabled = True
            p = db.get(Project, row.project_id)
            if p and p.archived:
                p.archived = False
                p.revision += 1
            row.status = "indexing"
            row.error = ""
            if not cfg.database_url.startswith("sqlite"):
                from hub.jobs import enqueue_knowledge

                enqueue_knowledge(db, cfg, row.id, row.revision)
            db.commit()
            result = info(db, row)
        if cfg.database_url.startswith("sqlite"):
            job = asyncio.create_task(
                index_connection(factory, cfg, connection_id, result["revision"])
            )
            app.state.tasks.add(job)
            job.add_done_callback(app.state.tasks.discard)
        return result

    @app.patch("/api/knowledge-sources/{connection_id}/control")
    def control(connection_id: str, body: ConnectionControl, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            row = db.get(KnowledgeConnection, connection_id)
            if not row or row.revision != body.revision:
                raise HTTPException(409, "Wissensquelle inzwischen geändert")
            row.enabled = body.enabled
            row.revision += 1
            if not body.enabled and row.status == "indexing":
                row.status = "paused"
            p = db.get(Project, row.project_id)
            if p:
                p.archived = not body.enabled
                p.revision += 1
            db.commit()
            return info(db, row)
