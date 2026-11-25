"""Asynchronous local derivatives with atomic claiming and manual-title precedence."""

import asyncio
import hashlib
import re
import unicodedata
from collections.abc import Sequence
from typing import Any, Protocol, cast

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from hub.config import Settings
from hub.db import Conversation, Message, ProviderConfig
from hub.policy import ContextPart, Privacy


class TitleProvider(Protocol):
    async def title(self, parts: list[ContextPart], roles: list[str]) -> str: ...


def initial_title(content: str) -> str:
    """A private local derivative, never requiring provider availability.

    Credential-looking input gets a neutral title rather than copying a secret
    into the sidebar. The complete message remains in its existing storage.
    """
    text = content[:12000]
    if re.search(
        r"(?i)(?:password|passwort|passwd|secret|api[ _-]?key|access[ _-]?token|"
        r"bearer\s|private[ _-]?key|ssh-(?:rsa|ed25519)|-----BEGIN|"
        r"\bsk-[A-Za-z0-9]|[A-Za-z0-9_+/=-]{32,})", text
    ):
        return "Vertrauliche Anfrage"
    text = re.sub(r"https?://\S+|\b[^\s@]+@[^\s@]+\.[^\s@]+", "", text)
    text = " ".join(
        "".join(c if not unicodedata.category(c).startswith("C") else " " for c in text).split()
    ).strip(" #*`>\"'")
    if not text:
        return "Neue Anfrage"
    if len(text) > 76:
        text = text[:73].rsplit(" ", 1)[0] or text[:73]
        text += "…"
    return text


def ensure_initial_title(db: Session, chat_id: str) -> None:
    """Persist immediately in the message transaction; manual titles always win."""
    repair_initial_titles(db, [chat_id])


def repair_initial_titles(db: Session, chat_ids: Sequence[str]) -> None:
    """Repair only visible legacy placeholders, with one bounded source-row query.

    Failed/interrupted refinements keep their state and are never redispatched.
    The window selects one actual user input per conversation, not all history.
    """
    if not chat_ids:
        return
    eligible = (
        Conversation.id.in_(chat_ids), Conversation.purpose == "chat",
        Conversation.archived.is_(False), Conversation.manual_title.is_(False),
        Conversation.title == "Neues Gespräch",
    )
    first = select(
        Message.conversation_id.label("chat_id"), Message.content,
        func.row_number().over(
            partition_by=Message.conversation_id, order_by=(Message.created, Message.id)
        ).label("position"),
    ).join(Conversation, Conversation.id == Message.conversation_id).where(
        *eligible, Message.active.is_(True), Message.role == "user"
    ).subquery()
    for chat_id, content in db.execute(
        select(first.c.chat_id, first.c.content).where(first.c.position == 1)
    ):
        title = initial_title(content)
        values = {"title": title}
        if title == "Vertrauliche Anfrage":
            values["title_status"] = "generated"
        db.execute(
            update(Conversation).where(*eligible, Conversation.id == chat_id).values(**values)
        )


def reserve_title(db: Session, cfg: Settings, chat_id: str) -> None:
    ensure_initial_title(db, chat_id)
    claimed = db.scalar(
        update(Conversation)
        .where(
            Conversation.id == chat_id,
            Conversation.manual_title.is_(False),
            Conversation.purpose == "chat",
            Conversation.archived.is_(False),
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
    factory: sessionmaker[Session], providers: TitleProvider, chat_id: str,
    *, provider_binding: ProviderConfig | None = None,
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
            .where(Message.conversation_id == chat_id, Message.active.is_(True))
            .order_by(Message.created, Message.id)
            .limit(2)
        ).all()
        parts = [
            ContextPart(
                content=m.content[:3000],
                label=Privacy(m.label),
                source_id=m.id,
                revision=m.revision,
            )
            for m in messages
        ]
        roles = [m.role for m in messages]
    def message_state(items: Sequence[Message]) -> list[tuple[str, int, str, str, str]]:
        return [(m.id, m.revision, m.role, m.label, hashlib.sha256(m.content.encode()).hexdigest())
                for m in items]

    expected_messages = message_state(messages)
    previous_boundary = getattr(providers, "before_send", None)

    def boundary() -> None:
        if previous_boundary:
            previous_boundary()
        with factory() as current_db:
            chat = current_db.get(Conversation, chat_id)
            if not chat or chat.archived or chat.manual_title or chat.title_status != "running":
                raise PermissionError("Title source conversation changed while waiting")
            actual_messages = current_db.scalars(
                select(Message)
                .where(Message.conversation_id == chat_id, Message.active.is_(True))
                .order_by(Message.created, Message.id).limit(2)
            ).all()
            if message_state(actual_messages) != expected_messages:
                raise PermissionError("Title source messages changed while waiting")
            if provider_binding:
                actual_provider = current_db.get(ProviderConfig, provider_binding.id)
                if (not actual_provider or not actual_provider.enabled
                        or actual_provider.revision != provider_binding.revision):
                    raise PermissionError("Title provider changed while waiting")

    has_boundary_hook = hasattr(providers, "before_send")
    hook_provider = cast(Any, providers)
    values: dict[str, object] = {"title_status": "failed"}
    try:
        boundary()
        if has_boundary_hook:
            hook_provider.before_send = boundary
        async with asyncio.timeout(35):
            title = await providers.title(parts, roles)
        boundary()
        if not title.strip() or len(title) > 80 or any(ord(c) < 32 for c in title):
            raise ValueError("Invalid title")
        values = {"title": title.strip(), "title_status": "generated"}
    except asyncio.CancelledError:
        values = {"title_status": "interrupted"}
        raise
    except Exception:
        pass  # Keep the original title and chat answer; never persist provider error content.
    finally:
        if has_boundary_hook:
            hook_provider.before_send = previous_boundary
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
