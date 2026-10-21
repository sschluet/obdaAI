"""Bounded extractive conversation summaries, with exact source freshness checks."""

import hashlib
import json
import re
import time
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

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


def summarize_conversation(
    db: Session, conversation_id: str, *, owner_id: str = "owner", byte_budget: int = 3000
) -> ConversationSummary | None:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.archived or byte_budget < 128:
        return None
    messages = list(
        db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.active.is_(True),
                Message.role.in_(["user", "assistant"]),
            )
            .order_by(Message.created.desc(), Message.id.desc())
            .limit(100)
        )
    )
    if len(messages) < 12:
        return None
    # Pointers include omitted sources: a private omitted message cannot create a public summary.
    older = messages[8:]
    pointers = [message_pointer(message) for message in reversed(older)]
    pieces, used = [], 0
    selected = sorted(
        older,
        key=lambda message: (
            -int(
                bool(
                    re.search(
                        r"\b(entschieden|entscheidung|beschlossen|decision|vereinbart|ziel|plan)\b",
                        message.content,
                        re.I,
                    )
                )
            ),
            -message.created,
            message.id,
        ),
    )
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
            "omitted": len(older) - len(pieces),
            "recent_excluded": 8,
            "window_limit": 100,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(content.encode()).hexdigest()
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
    db: Session, conversation_id: str, *, owner_id: str = "owner"
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
        return row
    except (ValueError, TypeError):
        return None


def invalidate_summary(db: Session, conversation_id: str) -> None:
    db.execute(
        delete(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id)
    )
