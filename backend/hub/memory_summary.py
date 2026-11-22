"""Bounded extractive conversation summaries, with exact source freshness checks."""

import hashlib
import json
import time
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, case, delete, func, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from hub.db import Base, Conversation, Memory, Message
from hub.memory_service import SENSITIVE


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[str] = mapped_column(String(36), default="owner")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_snapshot: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(20), default="LOCAL_ONLY")
    sha256: Mapped[str] = mapped_column(String(64))
    updated: Mapped[float] = mapped_column(Float, default=time.time)


class ConversationSummarySegment(Base):
    """Bounded source excerpts, retained across rolling summary projections."""

    __tablename__ = "conversation_summary_segments"
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    source_revision: Mapped[int] = mapped_column(Integer)
    source_sha256: Mapped[str] = mapped_column(String(64))
    excerpt: Mapped[str] = mapped_column(Text)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


def message_pointer(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "revision": message.revision,
        "sha256": hashlib.sha256(message.content.encode()).hexdigest(),
        "label": message.label,
    }


def _forgotten(db: Session, conversation_id: str) -> tuple[set[str], set[str]]:
    rows = list(
        db.scalars(select(Memory).where(Memory.status == "forgotten", Memory.owner_id == "owner"))
    )
    return (
        {
            row.source_message_id
            for row in rows
            if row.source_message_id and row.source_conversation_id == conversation_id
        },
        {row.sha256 for row in rows},
    )


def digest_message(message: Message) -> str:
    return hashlib.sha256(message.content.encode()).hexdigest()


def _segment_messages(
    db: Session,
    conversation_id: str,
    recent: list[str],
    question: str,
) -> list[Message]:
    from hub.knowledge import query_terms

    terms = query_terms(question)
    score: ColumnElement[Any] = sum(
        (
            case((ConversationSummarySegment.excerpt.icontains(term, autoescape=True), 3), else_=0)
            for term in terms
        ),
        start=case((Message.id == "", 0), else_=0),
    )
    for cue in ("entscheidung", "entschieden", "beschlossen", "decision", "ziel", "plan"):
        score += case(
            (ConversationSummarySegment.excerpt.icontains(cue, autoescape=True), 1), else_=0
        )
    rows = db.execute(
        select(Message, ConversationSummarySegment.source_sha256)
        .join(
            ConversationSummarySegment,
            ConversationSummarySegment.message_id == Message.id,
        )
        .where(
            Message.conversation_id == conversation_id,
            Message.active.is_(True),
            Message.role.in_(["user", "assistant"]),
            Message.id.not_in(recent),
            ConversationSummarySegment.excerpt != "",
            ConversationSummarySegment.source_revision == Message.revision,
        )
        .order_by(score.desc(), Message.created.desc(), Message.id)
        .limit(100)
    )
    return [message for message, source_sha in rows if digest_message(message) == source_sha]


def summarize_conversation(
    db: Session,
    conversation_id: str,
    *,
    owner_id: str = "owner",
    byte_budget: int = 3000,
    question: str = "",
    persist: bool = True,
) -> ConversationSummary | None:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.archived or byte_budget < 128:
        return None
    total = (
        db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.active.is_(True),
                Message.role.in_(["user", "assistant"]),
            )
        )
        or 0
    )
    if total < 12:
        return None
    recent = list(
        db.scalars(
            select(Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.active.is_(True),
                Message.role.in_(["user", "assistant"]),
            )
            .order_by(Message.created.desc(), Message.id.desc())
            .limit(8)
        )
    )
    forgotten_ids, forgotten_hashes = _forgotten(db, conversation_id)
    # Backfill a short resumable slice on each completed conversation. Segments
    # already created remain searchable even after their source falls beyond 100.
    pending = db.scalars(
        select(Message)
        .outerjoin(
            ConversationSummarySegment,
            ConversationSummarySegment.message_id == Message.id,
        )
        .where(
            Message.conversation_id == conversation_id,
            Message.active.is_(True),
            Message.role.in_(["user", "assistant"]),
            Message.id.not_in(recent),
            or_(
                ConversationSummarySegment.message_id.is_(None),
                ConversationSummarySegment.source_revision != Message.revision,
            ),
        )
        .order_by(Message.created, Message.id)
        .limit(200)
    )
    for message in pending if persist else []:
        segment = db.get(ConversationSummarySegment, message.id)
        if segment is None:
            segment = ConversationSummarySegment(
                message_id=message.id, conversation_id=conversation_id
            )
            db.add(segment)
        blocked = (
            message.id in forgotten_ids
            or digest_message(message) in forgotten_hashes
            or bool(SENSITIVE.search(message.content))
        )
        segment.source_revision, segment.source_sha256 = message.revision, digest_message(message)
        segment.excerpt = (
            "" if blocked else message.content.encode()[:1000].decode("utf-8", errors="ignore")
        )
        segment.updated = time.time()
    db.flush()
    messages = _segment_messages(db, conversation_id, recent, question)
    older = messages
    pointers = [message_pointer(message) for message in reversed(older)]
    pieces, used = [], 0
    selected = older  # SQL has ranked the complete retained segment corpus for this query.
    included = []
    forgotten_ids, forgotten_hashes = _forgotten(db, conversation_id)
    for message in selected:
        if (
            message.id in forgotten_ids
            or hashlib.sha256(message.content.encode()).hexdigest() in forgotten_hashes
        ):
            continue
        if SENSITIVE.search(message.content):
            continue  # Sensitive originals require dedicated review, never a summary bypass.
        prefix = f"[{message.role} {message.id}] "
        available = min(400, max(0, byte_budget - used - len(prefix.encode()) - 1))
        if available < 32:
            break
        quote = message.content.encode()[:available].decode("utf-8", errors="ignore")
        piece = prefix + quote
        pieces.append(piece)
        included.append(message.id)
        used += len(piece.encode()) + 1
    content = "\n".join(reversed(pieces))
    if not pieces:
        return None
    snapshot = json.dumps(
        {
            "sources": pointers,
            "included": included,
            "omitted": max(0, total - 8 - len(pieces)),
            "recent_excluded": 8,
            "window_limit": 100,
            "segmented": True,
            "backfill_pending": max(
                0,
                total
                - 8
                - (
                    db.scalar(
                        select(func.count())
                        .select_from(ConversationSummarySegment)
                        .where(ConversationSummarySegment.conversation_id == conversation_id)
                    )
                    or 0
                ),
            ),
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(content.encode()).hexdigest()
    if not persist:
        return ConversationSummary(
            conversation_id=conversation_id,
            owner_id=owner_id,
            revision=int(hashlib.sha256((snapshot + digest).encode()).hexdigest()[:7], 16) + 1,
            source_snapshot=snapshot,
            content=content,
            sha256=digest,
            label="LOCAL_ONLY",
        )
    row = db.get(ConversationSummary, conversation_id)
    if row and row.owner_id != owner_id:
        return None
    if row is None:
        row = ConversationSummary(conversation_id=conversation_id, owner_id=owner_id, revision=1)
        db.add(row)
    elif row.source_snapshot == snapshot and row.sha256 == digest:
        return row
    else:
        row.revision += 1
    row.source_snapshot, row.content, row.sha256 = snapshot, content, digest
    # Summaries are private derivatives, even when individual current messages are shareable.
    row.label, row.updated = "LOCAL_ONLY", time.time()
    return row


def fresh_summary(
    db: Session,
    conversation_id: str,
    *,
    owner_id: str = "owner",
    question: str = "",
    byte_budget: int = 3000,
) -> ConversationSummary | None:
    conversation = db.get(Conversation, conversation_id, populate_existing=True)
    row = db.get(ConversationSummary, conversation_id, populate_existing=True)
    if not row or row.owner_id != owner_id or not conversation or conversation.archived:
        return None
    try:
        document = json.loads(row.source_snapshot)
        forgotten_ids, forgotten_hashes = _forgotten(db, conversation_id)
        for pointer in document["sources"]:
            if pointer["id"] in document["included"] and (
                pointer["id"] in forgotten_ids or pointer["sha256"] in forgotten_hashes
            ):
                return None
            message = db.get(Message, pointer["id"], populate_existing=True)
            if (
                not message
                or not message.active
                or message.conversation_id != conversation_id
                or message.role not in {"user", "assistant"}
                or pointer != message_pointer(message)
            ):
                return None
        if row.sha256 != hashlib.sha256(row.content.encode()).hexdigest():
            return None
        if question:
            return summarize_conversation(
                db,
                conversation_id,
                owner_id=owner_id,
                question=question,
                persist=False,
                byte_budget=byte_budget,
            )
        return row
    except (ValueError, TypeError):
        return None


def invalidate_summary(db: Session, conversation_id: str) -> None:
    db.execute(
        delete(ConversationSummarySegment).where(
            ConversationSummarySegment.conversation_id == conversation_id
        )
    )
    db.execute(
        delete(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id)
    )
