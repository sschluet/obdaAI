"""Asynchronous local derivatives with atomic claiming and manual-title precedence."""

import asyncio
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from hub.config import Settings
from hub.db import Conversation, Message
from hub.policy import ContextPart, Privacy


class TitleProvider(Protocol):
    async def title(self, parts: list[ContextPart], roles: list[str]) -> str: ...


def reserve_title(db: Session, cfg: Settings, chat_id: str) -> None:
    claimed = db.scalar(
        update(Conversation)
        .where(
            Conversation.id == chat_id,
            Conversation.manual_title.is_(False),
            Conversation.title == "Neues Gespräch",
            Conversation.title_status == "idle",
        )
        .values(title_status="queued")
        .returning(Conversation.id)
    )
    if claimed and not cfg.database_url.startswith("sqlite"):
        # Defer on the same transaction as the successful answer and reservation.
        from hub.jobs import enqueue_title

        enqueue_title(db, cfg, chat_id)


async def execute_title(
    factory: sessionmaker[Session], providers: TitleProvider, chat_id: str
) -> None:
    with factory() as db:
        # A redispatched interrupted attempt is reconciled, never silently repeated.
        db.execute(
            update(Conversation)
            .where(
                Conversation.id == chat_id,
                Conversation.title_status == "running",
                Conversation.manual_title.is_(False),
            )
            .values(title_status="interrupted")
        )
        claimed = db.scalar(
            update(Conversation)
            .where(
                Conversation.id == chat_id,
                Conversation.title_status == "queued",
                Conversation.manual_title.is_(False),
            )
            .values(title_status="running")
            .returning(Conversation.id)
        )
        db.commit()
        if not claimed:
            return
        messages = db.scalars(
            select(Message)
            .where(Message.conversation_id == chat_id)
            .order_by(Message.created, Message.id)
            .limit(2)
        ).all()
        parts = [
            ContextPart(
                content=m.content[:3000], label=Privacy(m.label), source_id=m.id, revision=1
            )
            for m in messages
        ]
        roles = [m.role for m in messages]
    values: dict[str, object] = {"title_status": "failed"}
    try:
        async with asyncio.timeout(35):
            title = await providers.title(parts, roles)
        if not title.strip() or len(title) > 80 or any(ord(c) < 32 for c in title):
            raise ValueError("Invalid title")
        values = {"title": title.strip(), "title_status": "generated"}
    except asyncio.CancelledError:
        values = {"title_status": "interrupted"}
        raise
    except Exception:
        pass  # Keep the original title and chat answer; never persist provider error content.
    finally:
        with factory() as db:
            db.execute(
                update(Conversation)
                .where(
                    Conversation.id == chat_id,
                    Conversation.manual_title.is_(False),
                    Conversation.title_status == "running",
                )
                .values(**values)
            )
            db.commit()
