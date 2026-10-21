"""One context assembly path for provider-independent, revocable memory."""

import asyncio
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from hub.config import Settings
from hub.db import Conversation
from hub.memory_retrieval import project_memory, refresh_memory, select_memory
from hub.policy import CloudGrant, ContextPart, Privacy


class MemoryChanged(PermissionError):
    """Raised before transport when an admitted memory was revoked or changed."""


def freeze_memory(
    db: Session, cfg: Settings, conversation: Conversation, question: str
) -> dict[str, Any]:
    try:
        with db.begin_nested():
            return select_memory(db, cfg, conversation, question, byte_budget=2400)
    except Exception:
        return {"items": [], "summary": None, "used_bytes": 0, "degraded": True}


async def prepare_memory(
    factory: sessionmaker[Session], cfg: Settings, conversation: Conversation,
    question: str, frozen: dict[str, Any],
) -> dict[str, Any]:
    """Optional independent local query embedding; errors keep lexical selection usable."""
    from hub.memory_embeddings import embed
    from hub.memory_settings import get_settings

    try:
        with factory() as db:
            options = get_settings(db)
            enabled = options["enabled"] and options["config"]["embedding_enabled"]
        if not enabled or not cfg.memory_embedding_base_url or not cfg.memory_embedding_model:
            return frozen
        async with asyncio.timeout(2):
            vector = await embed(cfg, question)
        if vector is None:
            return frozen
        with factory() as db:
            return select_memory(db, cfg, conversation, question, query_vector=vector)
    except Exception:
        return frozen


def projection(
    factory: sessionmaker[Session], snapshot: dict[str, Any], *, external: bool,
    provider_id: str, byte_budget: int = 2400,
) -> tuple[list[ContextPart], list[CloudGrant], dict[str, Any]]:
    try:
        with factory() as db:
            current = refresh_memory(db, snapshot)
            available = project_memory(current, external=external, provider_id=provider_id)
        parts: list[ContextPart] = []
        used = 0
        for part in available:
            cost = len(part.content.encode()) + 64
            if used + cost <= byte_budget:
                parts.append(part)
                used += cost
        grants = [
            CloudGrant(source_id=p.source_id, revision=p.revision, provider_id=provider_id)
            for p in parts if external and p.label == Privacy.CLOUD_ALLOWED
        ]
        return parts, grants, {
            "included": [{"id": p.source_id, "revision": p.revision} for p in parts],
            "omitted": max(0, len(snapshot.get("items", [])) - len(parts)),
            "used_bytes": used, "degraded": False,
        }
    except Exception:
        return [], [], {"included": [], "omitted": 0, "used_bytes": 0, "degraded": True}


def boundary_guard(
    factory: sessionmaker[Session], snapshot: dict[str, Any], admitted: list[ContextPart], *,
    external: bool, provider_id: str, byte_budget: int,
) -> Any:
    """Shared synchronous callback checked at the final transport boundary."""
    expected = [p.model_dump(mode="json") for p in admitted]

    def check() -> None:
        actual, _, audit = projection(
            factory, snapshot, external=external, provider_id=provider_id, byte_budget=byte_budget
        )
        if audit["degraded"] or [p.model_dump(mode="json") for p in actual] != expected:
            raise MemoryChanged("Memory-Kontext wurde geändert; vor Versand verworfen")

    return check
