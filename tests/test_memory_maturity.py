"""Synthetic regressions for long-term memory identity, recall and explicit lifecycle control."""

import json

import pytest
from hub.config import Settings
from hub.db import Base, Conversation, Memory, MemoryRevision, Message, Project, Run
from hub.memory_embeddings import MemoryEmbedding, configuration
from hub.memory_learning import (
    ExtractedFact,
    Extraction,
    apply_extraction,
    learnable_source,
    reserve_learning,
    retry_learning_job,
)
from hub.memory_models import MemoryCandidate, MemoryLearningJob, MemorySettings
from hub.memory_retrieval import select_memory
from hub.memory_service import (
    SourcePointer,
    create_app_memory,
    digest,
    memory_info,
    promote_memory,
    review_candidate,
)
from hub.memory_summary import (
    ConversationSummarySegment,
    fresh_summary,
    summarize_conversation,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Conversation(id="chat"))
        session.commit()
        yield session
    engine.dispose()


def source(db, text):
    run = Run(conversation_id="chat", status="succeeded")
    db.add(run)
    db.flush()
    message = Message(conversation_id="chat", run_id=run.id, role="user", content=text)
    db.add(message)
    db.commit()
    return run, message


def test_independent_decisions_and_plans_coexist_and_deduplicate(db):
    db.add(Project(id="project", name="Synthetic project"))
    db.commit()
    for predicate in ["decision", "plan"]:
        first = create_app_memory(
            db,
            content="PostgreSQL verwenden",
            category="project",
            project_id="project",
            predicate=predicate,
            fact_type=predicate,
        )
        second = create_app_memory(
            db,
            content="Tägliche Backups erstellen",
            category="project",
            project_id="project",
            predicate=predicate,
            fact_type=predicate,
        )
        repeated = create_app_memory(
            db,
            content="Tägliche Backups erstellen",
            category="project",
            project_id="project",
            predicate=predicate,
            fact_type=predicate,
        )
        assert first.id != second.id == repeated.id
        assert first.status == second.status == "active" and first.subject != second.subject


def test_candidate_approval_does_not_replace_until_specific_current_fact_is_selected(db):
    old = create_app_memory(db, content="Ich arbeite als Ingenieur", predicate="profession")
    _, message = source(db, "Ich arbeite als Lehrer")
    candidate = MemoryCandidate(
        source_message_id=message.id,
        source_message_revision=message.revision,
        source_conversation_id="chat",
        source_sha256=digest(message.content),
        quote_start=0,
        quote_end=len(message.content),
        predicate="profession",
        subject="user",
    )
    db.add(candidate)
    db.commit()
    with pytest.raises(ValueError, match="Prüfung"):
        review_candidate(db, candidate.id, approve=True, expected_revision=1)
    assert old.status == "active" and candidate.status == "pending"
    with pytest.raises(ValueError, match="geändert"):
        review_candidate(
            db,
            candidate.id,
            approve=True,
            expected_revision=1,
            replacement_memory_id=old.id,
            replacement_revision=99,
        )
    current = review_candidate(
        db,
        candidate.id,
        approve=True,
        expected_revision=1,
        replacement_memory_id=old.id,
        replacement_revision=old.revision,
    )
    assert old.status == "superseded" and current.status == "active"
    assert db.get(MemoryRevision, (old.id, 1)) is not None


@pytest.mark.parametrize(
    "quote,project",
    [
        ("Übrigens, ich arbeite als Ingenieur.", False),
        ("Meine Lieblingssprache ist Python.", False),
        ("Für unsere Migration haben wir beschlossen, PostgreSQL einzusetzen.", True),
    ],
)
def test_natural_direct_user_statements_enter_grounded_extraction(db, quote, project):
    if project:
        db.add(Project(id="project", name="Migration"))
        db.get(Conversation, "chat").project_id = "project"
        db.commit()
    assert learnable_source(quote, project=project)
    run, message = source(db, quote)
    identifier = reserve_learning(db, Settings(), run.id)
    assert identifier
    job = db.get(MemoryLearningJob, identifier)
    apply_extraction(
        db,
        job,
        Extraction(
            facts=[
                ExtractedFact(
                    quote=quote,
                    predicate="decision" if project else "preference",
                    confidence=1,
                    fact_type="decision" if project else "fact",
                )
            ]
        ),
    )
    assert list(db.scalars(select(Memory)))
    assert db.scalar(select(Memory)).source_sha256 == digest(message.content)


@pytest.mark.parametrize(
    "text",
    [
        'Zitat: "Ich bin Ingenieur."',
        "Beispiel: Ich bin Ingenieur.",
        "Nicht speichern. Ich bin Ingenieur.",
        "Ich möchte wissen, wie das geht.",
    ],
)
def test_untrusted_examples_and_explicit_opt_out_do_not_enter_learning(text):
    assert not learnable_source(text, project=True)


def test_failed_learning_has_three_explicit_revision_bound_attempts(db):
    run, _ = source(db, "Ich mag lange Wanderungen")
    identifier = reserve_learning(db, Settings(), run.id)
    job = db.get(MemoryLearningJob, identifier)
    db.commit()
    for attempt in [1, 2]:
        job.status = "failed"
        db.commit()
        retry_learning_job(db, job, expected_attempts=attempt)
        assert job.status == "queued" and job.attempts == attempt + 1
        db.commit()
        with pytest.raises(ValueError):
            retry_learning_job(db, job, expected_attempts=attempt)
    job.status = "failed"
    db.commit()
    with pytest.raises(ValueError):
        retry_learning_job(db, job, expected_attempts=3)


def test_learning_retry_rejects_changed_or_forgotten_source(db):
    run, message = source(db, "Ich mag lange Wanderungen")
    job = db.get(MemoryLearningJob, reserve_learning(db, Settings(), run.id))
    job.status = "failed"
    message.revision += 1
    db.commit()
    with pytest.raises(ValueError):
        retry_learning_job(db, job, expected_attempts=1)
    assert job.attempts == 1


def test_archive_is_visible_and_only_explicit_promotion_restores_independent_memory(db):
    _, message = source(db, "Ich mag SyntheticAlpha")
    row = create_app_memory(
        db,
        content=message.content,
        source=SourcePointer(message.id, message.revision, "chat", digest(message.content)),
        cloud_providers=["openrouter"],
    )
    db.commit()
    assert memory_info(row)["provenance_status"] == "current"
    db.get(Conversation, "chat").archived = True
    db.commit()
    info = memory_info(row)
    assert info["provenance_status"] == "archived_origin" and not info["context_eligible"]
    assert info["can_promote"]
    with pytest.raises(ValueError):
        promote_memory(db, row, expected_revision=999)
    promote_memory(db, row, expected_revision=row.revision)
    db.commit()
    assert memory_info(row)["context_eligible"]
    assert row.source_message_id is None and row.origin.startswith("promoted:")
    assert row.label == "LOCAL_ONLY" and json.loads(row.cloud_providers) == []


def test_cumulative_segments_retrieve_an_old_topic_after_more_than_100_messages(db):
    for i in range(130):
        db.add(
            Message(
                id=f"message-{i:03}",
                conversation_id="chat",
                role="user",
                content="SYNTHETIC-OLD-TOPIC verwenden wir weiterhin"
                if i == 0
                else f"Unrelated synthetic message {i}",
                created=float(i),
            )
        )
    db.commit()
    summarize_conversation(db, "chat")
    db.commit()
    assert db.get(ConversationSummarySegment, "message-000") is not None
    relevant = fresh_summary(db, "chat", question="SYNTHETIC-OLD-TOPIC")
    assert relevant and "SYNTHETIC-OLD-TOPIC" in relevant.content
    snapshot = select_memory(
        db, Settings(), db.get(Conversation, "chat"), "SYNTHETIC-OLD-TOPIC", byte_budget=2400
    )
    assert snapshot["summary"] and "SYNTHETIC-OLD-TOPIC" in snapshot["summary"]["content"]
    assert snapshot["used_bytes"] <= 2400
    db.get(Message, "message-000").revision += 1
    db.commit()
    # The stale segment must never be used, even before asynchronous refresh.
    relevant = fresh_summary(db, "chat", question="SYNTHETIC-OLD-TOPIC")
    assert relevant is None or "SYNTHETIC-OLD-TOPIC" not in relevant.content


def test_semantic_mode_keeps_old_lexical_matches_and_searches_old_vectors(db):
    cfg = Settings(
        local_base_url="http://127.0.0.1:11434/v1",
        local_allowed_ip="127.0.0.1",
        memory_embedding_base_url="http://127.0.0.1:11434/v1",
        memory_embedding_model="synthetic",
    )
    db.add(MemorySettings(id=1, config='{"embedding_enabled":true,"summary_enabled":false}'))
    for i in range(2001):
        content = "SyntheticOldKeyword" if i == 0 else f"Unrelated synthetic note {i}"
        db.add(
            Memory(
                id=f"memory-{i:04}",
                path=f"app/{i}",
                storage="app",
                category="knowledge",
                content=content,
                sha256=digest(content),
                updated=float(i + 1),
            )
        )
    db.commit()
    old = db.get(Memory, "memory-0000")
    _, model, fingerprint = configuration(cfg)
    db.add(
        MemoryEmbedding(
            memory_id=old.id,
            revision=old.revision,
            sha256=old.sha256,
            model=model,
            config_sha256=fingerprint,
            dimensions=2,
            vector="[1,0]",
        )
    )
    db.commit()
    for query in ["SyntheticOldKeyword", "SynonymWithoutLexicalOverlap"]:
        snapshot = select_memory(db, cfg, db.get(Conversation, "chat"), query, query_vector=[1, 0])
        assert any(item["id"] == old.id for item in snapshot["items"])
        assert snapshot["semantic_scan_truncated"] is False


def test_embedding_turn_budget_resumes_without_blocking_through_whole_backfill(db, monkeypatch):
    import asyncio

    from hub import memory_embeddings
    from sqlalchemy import func
    from sqlalchemy.orm import sessionmaker

    cfg = Settings(
        local_base_url="http://127.0.0.1:11434/v1",
        local_allowed_ip="127.0.0.1",
        memory_embedding_base_url="http://127.0.0.1:11434/v1",
        memory_embedding_model="synthetic",
    )
    db.add(MemorySettings(id=1, config='{"embedding_enabled":true}'))
    for index in range(2):
        create_app_memory(db, content=f"Synthetic preference {index}")
    db.commit()
    clock = [0.0]
    calls = []

    async def embed(config, content):
        calls.append(content)
        clock[0] += 3
        return [1.0, 0.0]

    monkeypatch.setattr(memory_embeddings, "embed", embed)
    monkeypatch.setattr(memory_embeddings.time, "monotonic", lambda: clock[0])
    factory = sessionmaker(bind=db.get_bind())
    first = asyncio.run(
        memory_embeddings.refresh_embeddings(factory, cfg, limit=20, time_budget_seconds=2)
    )
    assert first["indexed"] == 1 and len(calls) == 1
    second = asyncio.run(
        memory_embeddings.refresh_embeddings(factory, cfg, limit=20, time_budget_seconds=2)
    )
    assert second["indexed"] == 1 and len(calls) == 2
    assert db.scalar(select(func.count()).select_from(MemoryEmbedding)) == 2


def test_embedding_backfill_reaches_old_uncached_rows_beyond_2000_cached_recent_rows(
    db, monkeypatch
):
    import asyncio

    from hub import memory_embeddings
    from sqlalchemy.orm import sessionmaker

    cfg = Settings(
        local_base_url="http://127.0.0.1:11434/v1",
        local_allowed_ip="127.0.0.1",
        memory_embedding_base_url="http://127.0.0.1:11434/v1",
        memory_embedding_model="synthetic",
    )
    db.add(MemorySettings(id=1, config='{"embedding_enabled":true}'))
    _, model, fingerprint = configuration(cfg)
    for index in range(2001):
        content = f"Synthetic old corpus {index}"
        row = Memory(
            id=f"old-{index:04}",
            path=f"old/{index}",
            content=content,
            sha256=digest(content),
            storage="app",
            category="personal",
            updated=float(index + 1),
        )
        db.add(row)
        if index:
            db.add(
                MemoryEmbedding(
                    memory_id=row.id,
                    revision=1,
                    sha256=row.sha256,
                    model=model,
                    config_sha256=fingerprint,
                    dimensions=2,
                    vector="[1,0]",
                )
            )
    db.commit()
    observed = []

    async def embed(config, content):
        observed.append(content)
        return [1.0, 0.0]

    monkeypatch.setattr(memory_embeddings, "embed", embed)
    result = asyncio.run(
        memory_embeddings.refresh_embeddings(sessionmaker(bind=db.get_bind()), cfg)
    )
    assert observed == ["Synthetic old corpus 0"] and result["indexed"] == 1
