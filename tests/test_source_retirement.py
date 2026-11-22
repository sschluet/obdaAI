"""A folder/scope change cannot be undone by a queued or finishing parser."""

import asyncio
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hub.auth import require_session
from hub.config import Settings
from hub.db import Base, Project, Source, SourceChunk, SourceReadyEvent
from hub.knowledge import extract_source, original, store
from hub.knowledge_api import install_knowledge_api
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def snapshot(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    cfg = Settings(source_dir=str(tmp_path / "sources"))
    data = b"Synthetic retired folder document"
    with factory() as db:
        project = Project(name="Synthetic scoped snapshots", kind="knowledge")
        db.add(project)
        db.flush()
        source = Source(
            project_id=project.id,
            name="synthetic.txt",
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
        )
        db.add(source)
        db.flush()
        store(cfg, source, data)
        identifier = source.id
        db.commit()
    yield factory, cfg, identifier, data
    engine.dispose()


@pytest.mark.parametrize("status", ["superseded", "deleted"])
def test_delayed_queue_delivery_never_parses_a_retired_snapshot(snapshot, monkeypatch, status):
    factory, cfg, identifier, data = snapshot
    with factory() as db:
        db.get(Source, identifier).status = status
        db.commit()

    def forbidden(*args):
        pytest.fail("Retired snapshots must not be parsed again")

    monkeypatch.setattr("hub.knowledge.isolated_parse", forbidden)
    asyncio.run(extract_source(factory, cfg, identifier))
    with factory() as db:
        source = db.get(Source, identifier)
        assert source.status == status and original(cfg, source).read_bytes() == data
        assert not db.scalars(select(SourceChunk)).all()
        assert not db.scalars(select(SourceReadyEvent)).all()


@pytest.mark.parametrize("status", ["superseded", "deleted"])
@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("revision_bump", [False, True])
def test_finishing_parser_cannot_reactivate_or_fail_a_retired_snapshot(
    snapshot, monkeypatch, status, failure, revision_bump
):
    factory, cfg, identifier, data = snapshot

    def parse(*args):
        with factory() as db:
            row = db.get(Source, identifier)
            assert row.status == "extracting"
            row.status = status
            if revision_bump:
                row.revision += 1
            db.commit()
        if failure:
            raise ValueError("Synthetic parser failure after scope retirement")
        return {
            "chunks": [{"locator": "line 1", "content": "Synthetic old folder result"}],
            "notes": [],
        }

    monkeypatch.setattr("hub.knowledge.isolated_parse", parse)
    asyncio.run(extract_source(factory, cfg, identifier))
    with factory() as db:
        source = db.get(Source, identifier)
        assert source.status == status and original(cfg, source).read_bytes() == data
        assert not db.scalars(select(SourceChunk)).all()
        assert not db.scalars(select(SourceReadyEvent)).all()


@pytest.mark.parametrize("status", ["superseded", "deleted"])
def test_retry_api_cannot_restore_retired_scope(snapshot, status):
    factory, cfg, identifier, data = snapshot
    with factory() as db:
        row = db.get(Source, identifier)
        row.status = status
        project_id = row.project_id
        revision = row.revision
        db.commit()
    app = FastAPI()
    app.state.tasks = set()
    app.dependency_overrides[require_session] = lambda: None
    install_knowledge_api(app, cfg, factory)
    with TestClient(app) as client:
        response = client.post(f"/api/projects/{project_id}/sources/{identifier}/retry")
        assert response.status_code == 409
    with factory() as db:
        row = db.get(Source, identifier)
        assert row.status == status and row.revision == revision
        assert original(cfg, row).read_bytes() == data
        assert not app.state.tasks
