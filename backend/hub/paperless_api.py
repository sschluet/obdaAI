"""Authenticated Paperless reads and local-only selected integration context."""

import asyncio
import json
import re
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, HTTPException, Query, Response
from sqlalchemy.orm import Session, sessionmaker

from hub.config import Settings
from hub.integrations import Integration
from hub.knowledge_api import Auth
from hub.paperless_client import document, download, list_documents
from hub.policy import ContextPart, Privacy
from hub.provider_settings import decrypt


def current(db: Session, integration_id: str, revision: int) -> Integration:
    db.expire_all()
    row = db.get(Integration, integration_id)
    if not row or row.kind != "paperless":
        raise HTTPException(404, "Paperless-Verbindung nicht vorhanden")
    if not row.enabled:
        raise HTTPException(409, "Paperless-Verbindung ausgeschaltet")
    if row.revision != revision:
        raise HTTPException(409, "Paperless-Verbindung geändert; neu laden")
    return row


def credential(cfg: Settings, row: Integration) -> tuple[str, str]:
    if not row.encrypted_secret:
        raise ValueError("Missing credential")
    return json.loads(row.config)["url"], decrypt(
        cfg, "integration:" + row.id, row.encrypted_secret
    )


def perform(
    db: Session,
    cfg: Settings,
    integration_id: str,
    revision: int,
    operation: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    row = current(db, integration_id, revision)
    try:
        url, token = credential(cfg, row)
        with httpx.Client(
            verify=True, trust_env=False, follow_redirects=False, timeout=10
        ) as client:
            result = operation(client, cfg, url, token, *args, **kwargs)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError, InvalidTag, RecursionError):
        raise HTTPException(502, "Paperless-Zugang, Ziel oder Antwort prüfen") from None
    current(db, integration_id, revision)
    return result


def search_query(question: str) -> str:
    """Bounded literal terms only; never send archive search operators from model output."""
    stop = {
        "bitte",
        "paperless",
        "dokument",
        "dokumente",
        "unterlagen",
        "datei",
        "dateien",
        "suche",
        "suchen",
        "zeige",
        "zeigen",
        "finde",
        "finden",
        "analysiere",
        "analyse",
        "zusammen",
        "fasse",
        "zusammenfassung",
        "meine",
        "meinen",
        "meiner",
        "meinem",
        "welche",
        "welchen",
        "welcher",
        "diese",
        "dieser",
        "einen",
        "eine",
        "einer",
        "über",
        "kannst",
        "könntest",
        "erstelle",
        "the",
        "please",
        "find",
        "search",
        "documents",
        "document",
        "summarize",
        "from",
        "with",
        "that",
        "this",
    }
    words = list(
        dict.fromkeys(w for w in re.findall(r"[^\W_]{3,60}", question.lower()) if w not in stop)
    )
    return " OR ".join('"' + word + '"' for word in words[:8])[:500]


def _collect_context(
    factory: sessionmaker[Session], cfg: Settings, selection: dict[str, Any], question: str
) -> list[ContextPart]:
    """Use only explicitly frozen profiles; private OCR never enters cloud context."""
    parts: list[ContextPart] = []
    remaining = 12000
    deadline = time.monotonic() + 45
    exact = re.search(
        r"(?:paperless|dokument|document)\s*(?:#|nr\.?\s*)?(\d{1,9})\b", question, re.IGNORECASE
    )
    # Only current-question terms are sent to the explicitly selected private archive.
    query = search_query(question)
    for item in selection.get("bindings", []):
        if item.get("kind") != "paperless":
            continue
        integration_id, revision = str(item["id"]), int(item["revision"])
        if time.monotonic() > deadline:
            raise HTTPException(504, "Paperless-Kontextprüfung dauert zu lange")
        if exact:
            hits = [{"id": int(exact.group(1))}]
        else:
            with factory() as db:
                listing = perform(
                    db, cfg, integration_id, revision, list_documents, query=query, page_size=3
                )
            hits = listing["results"]
        for hit in hits:
            if time.monotonic() > deadline:
                raise HTTPException(504, "Paperless-Kontextprüfung dauert zu lange")
            with factory() as db:
                result = perform(db, cfg, integration_id, revision, document, hit["id"])
            text = (
                f"Paperless-Dokument {result['id']}: {result['title']}\n"
                f"Stand: {result.get('modified', '')}\n{result['content']}"
            )
            if len(text) > remaining or result.get("content_truncated"):
                notice = "\n[Auszug gekürzt; vollständiges Dokument in Paperless öffnen.]"
                text = text[: max(0, remaining - len(notice))] + notice[:remaining]
            if text:
                parts.append(
                    ContextPart(
                        content=text,
                        label=Privacy.LOCAL_ONLY,
                        source_id=f"paperless:{integration_id}:{hit['id']}",
                        revision=revision,
                    )
                )
                remaining -= len(text)
            if remaining <= 0:
                return parts
    if any(item.get("kind") == "paperless" for item in selection.get("bindings", [])) and not parts:
        parts.append(
            ContextPart(
                content="Paperless-Suche: Keine passenden Dokumente gefunden.",
                label=Privacy.LOCAL_ONLY,
                source_id="paperless-search",
                revision=1,
            )
        )
    return parts


async def collect_context(
    factory: sessionmaker[Session], cfg: Settings, selection: dict[str, Any], question: str
) -> list[ContextPart]:
    return await asyncio.to_thread(_collect_context, factory, cfg, selection, question)


def validate_selection(db: Session, selection: dict[str, Any]) -> None:
    for item in selection.get("bindings", []):
        if item.get("kind") == "paperless":
            current(db, str(item["id"]), int(item["revision"]))


def install_paperless_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/integrations/{integration_id}/paperless/documents")
    def listing(
        integration_id: UUID,
        auth: Auth,
        expected_revision: int = Query(ge=1),
        query: str = Query(default="", max_length=500),
        page: int = Query(default=1, ge=1, le=10000),
        page_size: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, Any]:
        with factory() as db:
            result = perform(
                db,
                cfg,
                str(integration_id),
                expected_revision,
                list_documents,
                query=query,
                page=page,
                page_size=page_size,
            )
            return {**result, "integration_id": str(integration_id), "revision": expected_revision}

    @app.get("/api/integrations/{integration_id}/paperless/documents/{document_id}")
    def detail(
        integration_id: UUID, document_id: int, auth: Auth, expected_revision: int = Query(ge=1)
    ) -> dict[str, Any]:
        with factory() as db:
            result = perform(db, cfg, str(integration_id), expected_revision, document, document_id)
            return {**result, "integration_id": str(integration_id), "revision": expected_revision}

    @app.get("/api/integrations/{integration_id}/paperless/documents/{document_id}/original")
    def original(
        integration_id: UUID, document_id: int, auth: Auth, expected_revision: int = Query(ge=1)
    ) -> Response:
        with factory() as db:
            data, mime = perform(
                db, cfg, str(integration_id), expected_revision, download, document_id
            )
            # Never reflect untrusted archive file names into HTTP headers.
            extension = {
                "application/pdf": ".pdf",
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "text/plain": ".txt",
                "text/csv": ".csv",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
            }.get(mime, ".bin")
            return Response(
                data,
                media_type=mime,
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="paperless-{document_id}{extension}"'
                    ),
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )
