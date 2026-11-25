"""Tasks reuse private project/memory retrieval and bind the exact admitted context."""

import json
from types import SimpleNamespace

import pytest
from hub.config import Settings
from hub.db import Base, Project, Source, SourceChunk
from hub.memory_service import create_app_memory
from hub.memory_task_context import MARKER, assemble_task_context, validate_task_context
from hub.task_model import context
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Project(id="project", name="Synthetic project", instructions="Use synthetic standards")
        )
        db.add(
            Source(
                id="source",
                project_id="project",
                name="Large synthetic source.txt",
                sha256="a" * 64,
                size=100000,
                status="ready",
            )
        )
        db.flush()
        for i in range(150):
            db.add(
                SourceChunk(
                    source_id="source",
                    locator=f"line-{i:03}",
                    content=(
                        "Migration PostgreSQL selected evidence"
                        if i == 149
                        else "Irrelevant filler " * 200
                    ),
                )
            )
        db.commit()
        yield db
    engine.dispose()


def binding():
    return {"id": "source", "revision": 1, "sha256": "a" * 64}


def test_task_uses_project_instructions_memory_and_ranked_subset_of_large_source(db):
    memory = create_app_memory(
        db,
        content="Ich bevorzuge kurze Antworten",
        category="preference",
        subject="response_style",
        predicate="preference",
    )
    db.commit()
    parts = assemble_task_context(db, Settings(), "Migration PostgreSQL", "project", [binding()])
    assert any("Use synthetic standards" in p.content for p in parts)
    assert any(p.source_id == memory.id for p in parts)
    assert any("selected evidence" in p.content for p in parts)
    assert sum(p.source_id == "source" for p in parts) < 150
    assert sum(len(p.content.encode()) for p in parts) < 14000
    assert all(p.label == "LOCAL_ONLY" for p in parts)
    validate_task_context(db, Settings(), "Migration PostgreSQL", parts)


@pytest.mark.parametrize("change", ["memory", "instructions", "source", "source-chunk"])
def test_current_task_context_revokes_on_relevant_data_change(db, change):
    memory = create_app_memory(db, content="Synthetic PostgreSQL preference", category="preference")
    db.commit()
    parts = assemble_task_context(db, Settings(), "PostgreSQL", "project", [binding()])
    if change == "memory":
        memory.deleted = True
    elif change == "instructions":
        db.get(Project, "project").instructions = "Changed synthetic standards"
    elif change == "source":
        db.get(Source, "source").revision += 1
    else:
        from sqlalchemy import select

        row = db.scalar(select(SourceChunk).where(SourceChunk.locator == "line-149"))
        row.content = "Changed PostgreSQL evidence"
    db.commit()
    with pytest.raises(PermissionError):
        validate_task_context(db, Settings(), "PostgreSQL", parts)


def test_other_project_source_and_forged_context_payload_are_rejected(db):
    db.get(Source, "source").project_id = "other-project"
    db.commit()
    with pytest.raises(PermissionError):
        assemble_task_context(db, Settings(), "PostgreSQL", "project", [binding()])
    db.get(Source, "source").project_id = "project"
    db.commit()
    parts = assemble_task_context(db, Settings(), "PostgreSQL", "project", [binding()])
    parts[0] = parts[0].model_copy(update={"content": "Forged protected project content"})
    with pytest.raises(PermissionError):
        validate_task_context(db, Settings(), "PostgreSQL", parts)


def test_ai_task_context_uses_the_same_bound_builder(db):
    spec = SimpleNamespace(project_id="project", sources=[], goal="PostgreSQL preference")
    parts, roles = context(db, spec, {"skills_checked": []}, Settings())
    assert len(parts) == len(roles)
    marker = next(p for p in parts if p.source_id == MARKER)
    assert json.loads(marker.content)["project_id"] == "project"
    assert any("Use synthetic standards" in p.content for p in parts)
    validate_task_context(db, Settings(), spec.goal, parts)
