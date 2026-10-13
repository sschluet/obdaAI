"""Import an explicitly selected Paperless OCR copy into an existing private project."""

import asyncio
import hashlib
from typing import Any, cast
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import Field
from sqlalchemy import func, select, text

from hub.action_api import StrictInput
from hub.db import Project, Source
from hub.db_locks import ownership_lock
from hub.knowledge import extract_source, store
from hub.knowledge_api import Auth, source_info
from hub.paperless_api import current, perform
from hub.paperless_client import document


class ImportInput(StrictInput):
    expected_revision: int = Field(ge=1)
    project_id: UUID


def install_paperless_import_api(app: FastAPI, cfg: Any, factory: Any) -> None:
    @app.post("/api/integrations/{integration_id}/paperless/documents/{document_id}/import")
    async def import_ocr(
        integration_id: UUID, document_id: int, body: ImportInput, auth: Auth
    ) -> dict[str, Any]:
        if not 1 <= document_id <= 999999999:
            raise HTTPException(422, "Ungültige Dokumentnummer")

        def fetch() -> dict[str, Any]:
            with factory() as db:
                return cast(
                    dict[str, Any],
                    perform(
                        db, cfg, str(integration_id), body.expected_revision, document, document_id
                    ),
                )

        result = await asyncio.to_thread(fetch)
        if result.get("content_truncated"):
            raise HTTPException(413, "OCR-Inhalt überschreitet die Importgrenze; Original abrufen")
        content = result.get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(422, "Dokument enthält keinen lesbaren OCR-Text")
        # The original in Paperless stays untouched. This file is explicitly an OCR copy.
        data = (
            f"Paperless-Dokument {document_id} · OCR-Kopie\n"
            + "Titel: "
            + result.get("title", "")
            + "\nStand: "
            + result.get("modified", "")
            + "\n\n"
            + content
        ).encode("utf-8")

        def persist() -> dict[str, Any]:
            with factory() as db:
                ownership_lock(db)
                current(db, str(integration_id), body.expected_revision)
                project = db.get(Project, str(body.project_id))
                if not project or project.archived:
                    raise HTTPException(404, "Aktiver Projektraum nicht gefunden")
                if db.bind is not None and db.bind.dialect.name == "postgresql":
                    db.execute(text("SELECT pg_advisory_xact_lock(791103042)"))
                total = db.scalar(select(func.sum(Source.size))) or 0
                count, used = db.execute(
                    select(func.count(Source.id), func.sum(Source.size)).where(
                        Source.project_id == project.id
                    )
                ).one()
                if total + len(data) > 2 * 1024**3:
                    raise HTTPException(413, "Gesamtgrenze: 2 GiB Quelldateien")
                if count >= 100 or (used or 0) + len(data) > 200 * 1024**2:
                    raise HTTPException(413, "Projektgrenze: 100 Quellen / 200 MiB")
                file_hash = hashlib.sha256(data).hexdigest()
                existing = db.scalar(
                    select(Source).where(
                        Source.project_id == project.id,
                        Source.name == f"Paperless-{document_id}-OCR.txt",
                        Source.sha256 == file_hash,
                    )
                )
                if existing:
                    return source_info(existing)
                source = Source(
                    project_id=project.id,
                    name=f"Paperless-{document_id}-OCR.txt",
                    size=len(data),
                    sha256=file_hash,
                    label="LOCAL_ONLY",
                )
                db.add(source)
                db.flush()
                store(cfg, source, data)
                if not cfg.database_url.startswith("sqlite"):
                    from hub.jobs import enqueue_source

                    enqueue_source(db, cfg, source.id)
                db.commit()
                return source_info(source)

        answer = await asyncio.to_thread(persist)
        if cfg.database_url.startswith("sqlite"):
            job = asyncio.create_task(extract_source(factory, cfg, answer["id"]))
            app.state.tasks.add(job)
            job.add_done_callback(app.state.tasks.discard)
        return answer
