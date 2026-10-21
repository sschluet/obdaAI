"""Time-ineligible memory cannot consume model calls or starve bounded indexing."""

import asyncio
import hashlib

import pytest
from hub.config import Settings
from hub.db import Base, Memory
from hub.memory_embeddings import MemoryEmbedding, refresh_embeddings, save_embedding
from hub.memory_models import MemorySettings
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

NOW = 1000.0


@pytest.fixture
def indexing(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(MemorySettings(id=1, revision=1, config='{"embedding_enabled":true}'))
        db.commit()
    monkeypatch.setattr("hub.memory_embeddings.time.time", lambda: NOW)
    cfg = Settings(
        local_endpoints_json='{"http://127.0.0.1:9123/v1":"127.0.0.1"}',
        memory_embedding_base_url="http://127.0.0.1:9123/v1",
        memory_embedding_model="synthetic-time-test",
    )
    yield factory, cfg
    engine.dispose()


def add(db: Session, identifier: str, *, updated: float = 1, **validity) -> Memory:
    content = "Synthetic temporal memory " + identifier
    row = Memory(
        id=identifier,
        path="app-memory/" + identifier,
        storage="app",
        content=content,
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        updated=updated,
        **validity,
    )
    db.add(row)
    return row


@pytest.mark.parametrize("invalid", [{"valid_until": NOW}, {"valid_from": NOW + 1}])
def test_ineligible_prefix_exceeding_entire_scan_cannot_starve_valid_memory(
    indexing, monkeypatch, invalid
):
    factory, cfg = indexing
    with factory() as db:
        # More than both the 20-item work batch and 2000-row candidate scan.
        for number in range(2001):
            add(db, f"ineligible-{number}", updated=2000 + number, **invalid)
        eligible = add(db, "eligible", valid_from=NOW, valid_until=NOW + 10)
        db.commit()
    calls = []

    async def embed(_cfg, content):
        calls.append(content)
        return [1.0, 0.0]

    monkeypatch.setattr("hub.memory_embeddings.embed", embed)
    result = asyncio.run(refresh_embeddings(factory, cfg, limit=1))
    assert result == {"indexed": 1, "unavailable": 0, "stale": 0}
    assert calls == [eligible.content]
    with factory() as db:
        assert [row.memory_id for row in db.scalars(select(MemoryEmbedding))] == [eligible.id]
    # A later tick neither recalls invalid entries nor repeatedly recomputes the valid one.
    assert asyncio.run(refresh_embeddings(factory, cfg, limit=1))["indexed"] == 0
    assert calls == [eligible.content]


@pytest.mark.parametrize("invalid", [{"valid_until": NOW}, {"valid_from": NOW + 1}])
def test_next_candidate_becomes_ineligible_before_http_and_is_not_dispatched(
    indexing, monkeypatch, invalid
):
    factory, cfg = indexing
    with factory() as db:
        first = add(db, "first", updated=2)
        second = add(db, "second", updated=1)
        db.commit()
    calls = []

    async def embed(_cfg, content):
        calls.append(content)
        with factory() as db:
            current = db.get(Memory, second.id)
            for key, value in invalid.items():
                setattr(current, key, value)
            db.commit()
        return [1.0, 0.0]

    monkeypatch.setattr("hub.memory_embeddings.embed", embed)
    result = asyncio.run(refresh_embeddings(factory, cfg, limit=2))
    assert result == {"indexed": 1, "unavailable": 0, "stale": 1}
    assert calls == [first.content]
    with factory() as db:
        assert db.get(MemoryEmbedding, first.id) is not None
        assert db.get(MemoryEmbedding, second.id) is None


@pytest.mark.parametrize("invalid", [{"valid_until": NOW}, {"valid_from": NOW + 1}])
def test_validity_revoked_during_http_cannot_persist_embedding(indexing, monkeypatch, invalid):
    factory, cfg = indexing
    with factory() as db:
        row = add(db, "revoked")
        db.commit()
    calls = []

    async def embed(_cfg, content):
        calls.append(content)
        with factory() as db:
            current = db.get(Memory, row.id)
            for key, value in invalid.items():
                setattr(current, key, value)
            db.commit()
        return [1.0, 0.0]

    monkeypatch.setattr("hub.memory_embeddings.embed", embed)
    assert asyncio.run(refresh_embeddings(factory, cfg)) == {
        "indexed": 0, "unavailable": 0, "stale": 1
    }
    assert calls == [row.content]
    with factory() as db:
        assert db.get(MemoryEmbedding, row.id) is None


@pytest.mark.parametrize("invalid", [{"valid_until": NOW}, {"valid_from": NOW + 1}])
def test_direct_embedding_save_rejects_time_ineligible_memory(indexing, invalid):
    factory, cfg = indexing
    with factory() as db:
        row = add(db, "direct", **invalid)
        db.commit()
        assert not save_embedding(db, cfg, row.id, row.revision, row.sha256, [1.0, 0.0])
        assert db.get(MemoryEmbedding, row.id) is None
