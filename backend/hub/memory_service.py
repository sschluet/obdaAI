"""Source-bound lifecycle on the existing Memory and MemoryRevision records."""

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from hub.db import Conversation, Memory, MemoryRevision, Message, Project, new_id
from hub.db_locks import ownership_lock
from hub.memory_models import MemoryCandidate

CATEGORIES = {"personal", "project", "conversation", "preference", "knowledge"}
FACT_TYPES = {"fact", "plan", "hypothesis", "decision"}
PREDICATES = {
    "name",
    "profession",
    "family",
    "location",
    "interest",
    "preference",
    "goal",
    "plan",
    "decision",
    "health",
    "finance",
    "belief",
    "other",
}
SENSITIVE = re.compile(
    r"\b(diagnos\w*|krank\w*|gesundheit\w*|medikament\w*|depress\w*|therap\w*|"
    r"health|medical|cancer|diabetes|religio\w*|politisch\w*|sexual\w*|gehalt|salary|"
    r"kontonummer|iban|schulden|debt|password|passwort|api.?key|token|secret|"
    r"krebs|hiv\w*|schwanger\w*|homosexuell\w*|bisexuell\w*|transgender|"
    r"verdiene|einkommen|income|bankkonto|strafe|vorbestraft\w*|"
    r"katholisch\w*|evangelisch\w*|muslim\w*|jüdisch\w*|atheist\w*)\b",
    re.I,
)


def digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def normalized(content: str) -> str:
    return " ".join(content.casefold().split())


@dataclass(frozen=True)
class SourcePointer:
    message_id: str
    revision: int
    conversation_id: str
    sha256: str


def fresh_source(db: Session, source: SourcePointer) -> Message:
    message = db.get(Message, source.message_id, populate_existing=True)
    chat = db.get(Conversation, source.conversation_id, populate_existing=True)
    if (
        not message
        or not chat
        or chat.archived
        or chat.purpose != "chat"
        or not message.active
        or message.role != "user"
        or message.conversation_id != source.conversation_id
        or message.revision != source.revision
        or digest(message.content) != source.sha256
    ):
        raise ValueError("Memory-Quelle ist nicht mehr aktuell")
    return message


def candidate_source(candidate: MemoryCandidate) -> SourcePointer:
    return SourcePointer(
        candidate.source_message_id,
        candidate.source_message_revision,
        candidate.source_conversation_id,
        candidate.source_sha256,
    )


def candidate_quote(db: Session, candidate: MemoryCandidate) -> str:
    content = fresh_source(db, candidate_source(candidate)).content
    if not 0 <= candidate.quote_start < candidate.quote_end <= len(content):
        raise ValueError("Memory-Quellenauswahl ungültig")
    if db.scalar(
        select(Memory.id).where(
            Memory.status == "forgotten",
            Memory.source_message_id == candidate.source_message_id,
        )
    ):
        raise ValueError("Memory-Quelle wurde ausdrücklich vergessen")
    return content[candidate.quote_start : candidate.quote_end]


def preserve_revision(db: Session, row: Memory) -> None:
    if not db.get(MemoryRevision, (row.id, row.revision)):
        db.add(
            MemoryRevision(
                memory_id=row.id, revision=row.revision, content=row.content, sha256=row.sha256
            )
        )


def create_app_memory(
    db: Session,
    *,
    content: str,
    title: str = "",
    category: str = "personal",
    fact_type: str = "fact",
    subject: str = "user",
    predicate: str = "other",
    sensitivity: str = "private",
    cloud_providers: tuple[str, ...] | list[str] = (),
    project_id: str | None = None,
    source: SourcePointer | None = None,
    explicit_correction: bool = False,
    confidence: float = 1.0,
    valid_from: float | None = None,
    valid_until: float | None = None,
    identifier: str | None = None,
    approved_sensitive: bool = False,
) -> Memory:
    ownership_lock(db)
    if category not in CATEGORIES or fact_type not in FACT_TYPES:
        raise ValueError("Ungültiger Memory-Typ")
    if not content.strip() or len(content) > 8000 or len(title) > 120:
        raise ValueError("Memory-Inhalt ungültig")
    if (
        not math.isfinite(confidence)
        or not 0 <= confidence <= 1
        or sensitivity not in {"public", "private", "sensitive"}
    ):
        raise ValueError("Memory-Metadaten ungültig")
    if len(subject) > 80 or len(predicate) > 80:
        raise ValueError("Memory-Schlüssel zu lang")
    if any(v is not None and not math.isfinite(v) for v in (valid_from, valid_until)):
        raise ValueError("Memory-Gültigkeitszeitraum ungültig")
    if valid_until is not None and valid_from is not None and valid_until <= valid_from:
        raise ValueError("Memory-Gültigkeitszeitraum ungültig")
    if category == "project" and not project_id:
        raise ValueError("Projekt-Memory benötigt ein Projekt")
    if project_id and (not (project := db.get(Project, project_id)) or project.archived):
        raise ValueError("Projekt nicht verfügbar")
    providers = list(dict.fromkeys(cloud_providers))
    if any(
        not isinstance(p, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", p) for p in providers
    ):
        raise ValueError("Cloudfreigabe ungültig")
    if source:
        current = fresh_source(db, source)
        if db.scalar(
            select(Memory.id).where(
                Memory.status == "forgotten",
                Memory.source_message_id == source.message_id,
            )
        ):
            raise ValueError("Memory-Quelle wurde ausdrücklich vergessen")
        if content not in current.content:
            raise ValueError("Memory muss ein wörtlicher Nutzerbeleg sein")
        if (sensitivity == "sensitive" or SENSITIVE.search(content)) and not approved_sensitive:
            raise ValueError("Sensible Fakten benötigen ausdrückliche Prüfung")
    text = ("# " + title + "\n\n" if title else "") + content.strip()
    matches = list(
        db.scalars(
            select(Memory).where(
                Memory.storage == "app",
                Memory.owner_id == "owner",
                Memory.project_id == project_id,
                Memory.subject == subject,
                Memory.predicate == predicate,
                Memory.category == category,
                Memory.status == "active",
                Memory.deleted.is_(False),
            )
        )
    )
    for previous in matches:
        if normalized(previous.content) == normalized(text):
            if (
                sorted(json.loads(previous.cloud_providers)) != sorted(providers)
                or previous.sensitivity != sensitivity
                or previous.fact_type != fact_type
            ):
                raise ValueError(
                    "Gleicher Inhalt mit anderen Freigaben vorhanden: "
                    + previous.id
                    + "; vorhandenes Memory mit aktueller Revision bearbeiten"
                )
            return previous
    # A known single-valued predicate may never have competing active values.
    conflicts = (
        [match for match in matches if match.fact_type == fact_type]
        if predicate not in {"other", "interest", "preference", "goal"}
        else []
    )
    if conflicts and not explicit_correction:
        raise ValueError("Widersprüchlicher Fakt benötigt Prüfung")
    identifier = identifier or new_id()
    existing = db.get(Memory, identifier)
    if existing:
        if (
            existing.storage == "app"
            and existing.content == text
            and not existing.deleted
            and existing.project_id == project_id
            and existing.category == category
            and existing.fact_type == fact_type
            and existing.predicate == predicate
            and existing.cloud_providers == json.dumps(providers)
        ):
            return existing
        raise ValueError("Memory-ID bereits verwendet")
    row = Memory(
        id=identifier,
        path="app-memory/" + identifier,
        origin="app",
        storage="app",
        owner_id="owner",
        category=category,
        fact_type=fact_type,
        status="active",
        subject=subject,
        predicate=predicate,
        confidence=confidence,
        sensitivity=sensitivity,
        cloud_providers=json.dumps(providers),
        valid_from=valid_from,
        valid_until=valid_until,
        project_id=project_id,
        content=text,
        base_content=text,
        sha256=digest(text),
        revision=1,
        writable=True,
        deleted=False,
        label="CLOUD_ALLOWED" if providers else "LOCAL_ONLY",
        conflict="",
        source_message_id=source.message_id if source else None,
        source_message_revision=source.revision if source else None,
        source_conversation_id=source.conversation_id if source else None,
        source_sha256=source.sha256 if source else "",
        supersedes_id=conflicts[-1].id if conflicts else None,
    )
    for old in conflicts:
        from hub.memory_embeddings import invalidate_memory

        invalidate_memory(db, old.id)
        preserve_revision(db, old)
        old.status = "superseded"
        old.revision += 1
        old.updated = time.time()
    db.add(row)
    db.flush()
    preserve_revision(db, row)
    return row


def edit_app_memory(
    db: Session,
    row: Memory,
    *,
    expected_revision: int,
    content: str,
    title: str = "",
    cloud_providers: list[str] | None = None,
    valid_until: float | None = None,
    valid_from: float | None = None,
    project_id: str | None = None,
    **metadata: Any,
) -> Memory:
    ownership_lock(db)
    db.refresh(row)
    if row.storage != "app" or row.owner_id != "owner" or row.deleted:
        raise ValueError("Aktives App-Memory nicht gefunden")
    if row.revision != expected_revision or row.status == "forgotten":
        raise ValueError("Memory inzwischen geändert")
    if not content.strip() or len(content) > 8000 or len(title) > 120:
        raise ValueError("Memory-Inhalt ungültig")
    if any(
        key not in {"category", "fact_type", "subject", "predicate", "sensitivity"}
        for key in metadata
    ):
        raise ValueError("Memory-Metadaten ungültig")
    if metadata.get("category", row.category) not in CATEGORIES:
        raise ValueError("Memory-Kategorie ungültig")
    if metadata.get("fact_type", row.fact_type) not in FACT_TYPES:
        raise ValueError("Memory-Faktentyp ungültig")
    if metadata.get("sensitivity", row.sensitivity) not in {"public", "private", "sensitive"}:
        raise ValueError("Memory-Sensitivität ungültig")
    if metadata.get("category", row.category) == "project" and not project_id:
        raise ValueError("Projekt-Memory benötigt ein Projekt")
    if project_id and (not (project := db.get(Project, project_id)) or project.archived):
        raise ValueError("Projekt nicht verfügbar")
    if any(v is not None and not math.isfinite(v) for v in (valid_from, valid_until)):
        raise ValueError("Memory-Gültigkeitszeitraum ungültig")
    if valid_until is not None and valid_from is not None and valid_until <= valid_from:
        raise ValueError("Memory-Gültigkeitszeitraum ungültig")
    if cloud_providers is not None and any(
        not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", p) for p in cloud_providers
    ):
        raise ValueError("Cloudfreigabe ungültig")
    from hub.memory_embeddings import invalidate_memory

    invalidate_memory(db, row.id)
    predicate = metadata.get("predicate", row.predicate)
    if predicate not in {"other", "interest", "preference", "goal", ""}:
        for competing in db.scalars(
            select(Memory).where(
                Memory.storage == "app",
                Memory.owner_id == "owner",
                Memory.id != row.id,
                Memory.project_id == project_id,
                Memory.status == "active",
                Memory.deleted.is_(False),
                Memory.category == metadata.get("category", row.category),
                Memory.fact_type == metadata.get("fact_type", row.fact_type),
                Memory.subject == metadata.get("subject", row.subject),
                Memory.predicate == predicate,
            )
        ):
            preserve_revision(db, competing)
            invalidate_memory(db, competing.id)
            competing.status = "superseded"
            competing.revision += 1
            competing.updated = time.time()
    preserve_revision(db, row)
    row.content = ("# " + title + "\n\n" if title else "") + content.strip()
    row.sha256 = digest(row.content)
    row.base_content = row.content
    row.revision += 1
    row.updated = time.time()
    row.valid_until = valid_until
    row.valid_from = valid_from
    row.project_id = project_id
    for key, value in metadata.items():
        setattr(row, key, value)
    if cloud_providers is not None:
        row.cloud_providers = json.dumps(list(dict.fromkeys(cloud_providers)))
        row.label = "CLOUD_ALLOWED" if cloud_providers else "LOCAL_ONLY"
    # A manual correction becomes authoritative; never misattribute it to an old quote.
    row.source_message_id = row.source_message_revision = None
    row.source_conversation_id = None
    row.source_sha256 = ""
    preserve_revision(db, row)
    return row


def forget_memory(db: Session, row: Memory, *, expected_revision: int) -> None:
    ownership_lock(db)
    db.refresh(row)
    if row.storage != "app" or row.owner_id != "owner" or row.revision != expected_revision:
        raise ValueError("Memory inzwischen geändert")
    # Explicit forgetting removes derived copies, not the user's original conversation.
    from hub.memory_embeddings import invalidate_memory
    from hub.memory_summary import ConversationSummary, invalidate_summary

    invalidate_memory(db, row.id)
    if row.source_conversation_id:
        invalidate_summary(db, row.source_conversation_id)
    else:
        db.execute(delete(ConversationSummary))
    for version in db.scalars(select(MemoryRevision).where(MemoryRevision.memory_id == row.id)):
        db.delete(version)
    row.content = row.base_content = row.conflict = ""
    row.cloud_providers = "[]"
    row.subject, row.predicate = "", ""
    row.status, row.deleted = "forgotten", True
    row.revision += 1
    # Retain only the one-way digest as a suppression tombstone, never the forgotten text.
    row.updated = time.time()


def memory_info(row: Memory) -> dict[str, Any]:
    result = {
        key: getattr(row, key)
        for key in (
            "id",
            "origin",
            "path",
            "project_id",
            "label",
            "revision",
            "sha256",
            "content",
            "conflict",
            "deleted",
            "writable",
            "updated",
        )
    }
    for key in (
        "storage",
        "owner_id",
        "category",
        "fact_type",
        "status",
        "subject",
        "predicate",
        "confidence",
        "sensitivity",
        "valid_from",
        "valid_until",
        "source_message_id",
        "source_message_revision",
        "source_conversation_id",
        "source_sha256",
        "supersedes_id",
    ):
        result[key] = getattr(row, key)
    result["cloud_providers"] = json.loads(row.cloud_providers)
    if row.status == "active" and row.valid_until is not None and row.valid_until <= time.time():
        result["status"] = "expired"
    return result


def review_candidate(
    db: Session, candidate_id: str, *, approve: bool, expected_revision: int
) -> Memory | None:
    candidate = db.get(MemoryCandidate, candidate_id, populate_existing=True)
    if (
        not candidate
        or candidate.owner_id != "owner"
        or candidate.status != "pending"
        or candidate.revision != expected_revision
    ):
        raise ValueError("Memory-Vorschlag inzwischen geändert")
    row = None
    if approve:
        quote = candidate_quote(db, candidate)
        source = candidate_source(candidate)
        message = fresh_source(db, source)
        chat = db.get(Conversation, message.conversation_id)
        row = create_app_memory(
            db,
            content=quote,
            category=candidate.category,
            fact_type=candidate.fact_type,
            subject=candidate.subject,
            predicate=candidate.predicate,
            sensitivity=candidate.sensitivity,
            confidence=candidate.confidence,
            source=source,
            explicit_correction=True,
            approved_sensitive=True,
            project_id=chat.project_id if chat and candidate.category == "project" else None,
        )
        candidate.memory_id = row.id
    candidate.status = "approved" if approve else "rejected"
    candidate.revision += 1
    return row
