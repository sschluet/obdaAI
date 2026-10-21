"""Optional local semantic index. Derived vectors remain in the application's database."""

import asyncio
import hashlib
import json
import math
import time
from typing import Any

import httpx
from sqlalchemy import Float, ForeignKey, Integer, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from hub.config import Settings, read_secret
from hub.db import Base, Memory
from hub.provider_settings import local_endpoints
from hub.providers import pinned_url


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(240))
    config_sha256: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[str] = mapped_column(Text)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


def configuration(cfg: Settings) -> tuple[str, str, str]:
    base = getattr(cfg, "memory_embedding_base_url", "")
    model = getattr(cfg, "memory_embedding_model", "")
    if (
        not base
        or not model
        or len(model) > 240
        or base not in local_endpoints(cfg)
        or "LOCAL_ONLY" not in cfg.local_allowed_labels
    ):
        raise ValueError("Local memory embedding model is not configured")
    fingerprint = hashlib.sha256(
        json.dumps([base, model, local_endpoints(cfg)[base]], separators=(",", ":")).encode()
    ).hexdigest()
    return base, model, fingerprint


def checked_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not 1 <= len(value) <= 3072:
        raise ValueError("Invalid embedding dimensions")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value):
        raise ValueError("Invalid embedding values")
    vector = [float(x) for x in value]
    if any(not math.isfinite(x) or abs(x) > 1e6 for x in vector):
        raise ValueError("Invalid embedding values")
    if not any(vector):
        raise ValueError("Empty embedding direction")
    return vector


async def embed(cfg: Settings, text: str) -> list[float] | None:
    """No cloud fallback. Caller may continue lexical retrieval when unavailable."""
    try:
        if not text or len(text.encode()) > 16000:
            return None
        base, model, _ = configuration(cfg)
        target, headers, extensions = pinned_url(
            base, "/embeddings", external=False, allowed_ip=local_endpoints(cfg)[base]
        )
        key_file = getattr(cfg, "memory_embedding_key_file", "")
        if key_file:
            headers["Authorization"] = "Bearer " + read_secret(key_file)
        async with (
            asyncio.timeout(8),
            httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client,
        ):
            async with client.stream(
                "POST",
                target,
                headers=headers,
                extensions=extensions,
                json={"model": model, "input": text, "encoding_format": "float"},
            ) as response:
                response.raise_for_status()
                data = bytearray()
                async for block in response.aiter_bytes():
                    data.extend(block)
                    if len(data) > 200000:
                        return None
        payload = json.loads(data)
        if not isinstance(payload, dict) or payload.get("model", model) != model:
            return None
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("index", 0) != 0:
            return None
        return checked_vector(rows[0]["embedding"])
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OSError,
        TimeoutError,
        httpx.HTTPError,
    ):
        return None


def save_embedding(
    db: Session, cfg: Settings, memory_id: str, revision: int, sha256: str, vector: list[float]
) -> bool:
    """Recheck current content after the asynchronous call before saving derivatives."""
    row = db.get(Memory, memory_id, populate_existing=True)
    if not row or row.deleted or row.revision != revision or row.sha256 != sha256:
        return False
    if (
        row.status != "active"
        or row.conflict
        or row.owner_id != "owner"
        or (row.valid_until is not None and row.valid_until <= time.time())
        or row.sha256 != hashlib.sha256(row.content.encode()).hexdigest()
    ):
        return False
    _, model, fingerprint = configuration(cfg)
    values = checked_vector(vector)
    item = db.get(MemoryEmbedding, memory_id)
    if item is None:
        item = MemoryEmbedding(memory_id=memory_id)
        db.add(item)
    item.revision, item.sha256 = revision, sha256
    item.model, item.config_sha256 = model, fingerprint
    item.dimensions, item.vector, item.updated = len(values), json.dumps(values), time.time()
    return True


def similarity(left: list[float], right: list[float]) -> float:
    left, right = checked_vector(left), checked_vector(right)
    if len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / math.sqrt(
        sum(a * a for a in left) * sum(b * b for b in right)
    )


def invalidate_memory(db: Session, memory_id: str) -> None:
    db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == memory_id))


async def refresh_embeddings(
    factory: sessionmaker[Session], cfg: Settings, *, limit: int = 20
) -> dict[str, int]:
    """Bounded existing-worker backfill; settings/revisions checked again after every call."""
    from hub.memory_settings import get_settings

    result = {"indexed": 0, "unavailable": 0, "stale": 0}
    if limit <= 0:
        return result
    try:
        _, _, fingerprint = configuration(cfg)
    except ValueError:
        return result
    with factory() as db:
        settings = get_settings(db)
        if not settings.get("enabled", True) or not settings["config"].get(
            "embedding_enabled", False
        ):
            return result
        revision = settings["revision"]
        candidates = []
        for row in db.scalars(
            select(Memory)
            .where(Memory.deleted.is_(False), Memory.status == "active", Memory.owner_id == "owner")
            .order_by(Memory.updated.desc())
            .limit(2000)
        ):
            cached = db.get(MemoryEmbedding, row.id)
            if (
                cached
                and cached.sha256 == row.sha256
                and cached.revision == row.revision
                and cached.config_sha256 == fingerprint
            ):
                continue
            if row.conflict or row.sha256 != hashlib.sha256(row.content.encode()).hexdigest():
                continue
            candidates.append((row.id, row.revision, row.sha256, row.content))
            if len(candidates) >= min(50, max(0, limit)):
                break
    for memory_id, source_revision, sha256, content in candidates:
        with factory() as db:
            current = get_settings(db)
            if (
                current["revision"] != revision
                or not current.get("enabled", True)
                or not current["config"].get("embedding_enabled", False)
            ):
                break
            current_memory = db.get(Memory, memory_id)
            if (
                not current_memory
                or current_memory.deleted
                or current_memory.status != "active"
                or current_memory.revision != source_revision
                or current_memory.sha256 != sha256
            ):
                result["stale"] += 1
                continue
        vector = await embed(cfg, content)
        if vector is None:
            result["unavailable"] += 1
            continue
        with factory() as db:
            current = get_settings(db)
            if (
                current["revision"] != revision
                or not current.get("enabled", True)
                or not current["config"].get("embedding_enabled", False)
            ):
                break
            if save_embedding(db, cfg, memory_id, source_revision, sha256, vector):
                db.commit()
                result["indexed"] += 1
            else:
                result["stale"] += 1
    return result
