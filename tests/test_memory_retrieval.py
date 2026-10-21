import asyncio
import hashlib
import json
import time

import pytest
from hub.config import Settings
from hub.db import Base, Conversation, Memory, Message, Project
from hub.memory_embeddings import MemoryEmbedding, configuration, refresh_embeddings, save_embedding
from hub.memory_models import MemorySettings
from hub.memory_retrieval import project_memory, refresh_memory, select_memory
from hub.memory_summary import fresh_summary, summarize_conversation
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Conversation(id="chat"))
        session.commit()
        yield session
    engine.dispose()


def memory(db, text="Ich bevorzuge Python", **kwargs):
    row = Memory(
        content=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        path="app/" + str(time.time_ns()),
        storage="app",
        category="preference",
        **kwargs,
    )
    db.add(row)
    db.commit()
    return row


def selected(db, question="Was bevorzuge ich bei Python?", **kwargs):
    return select_memory(db, Settings(), db.get(Conversation, "chat"), question, **kwargs)


def test_relevant_app_memory_without_global_vault_inheritance(db):
    personal = memory(db)
    vault = Memory(
        content="Python Vault",
        sha256=hashlib.sha256(b"Python Vault").hexdigest(),
        path="existing.md",
        storage="vault",
    )
    db.add(vault)
    db.commit()
    assert [r["id"] for r in selected(db)["items"]] == [personal.id]
    assert not selected(db, "Wetter in Tokio")["items"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("deleted", True),
        ("status", "forgotten"),
        ("status", "candidate"),
        ("status", "superseded"),
        ("conflict", "conflict"),
        ("owner_id", "other"),
        ("valid_until", 1),
        ("valid_from", 9999999999),
    ],
)
def test_inactive_or_out_of_scope_never_selected(db, field, value):
    memory(db, **{field: value})
    assert not selected(db)["items"]


@pytest.mark.parametrize("mutation", ["delete", "edit", "share", "expiry", "disable"])
def test_refresh_revokes_frozen_context(db, mutation):
    row = memory(db)
    snapshot = selected(db)
    assert snapshot["items"]
    if mutation == "delete":
        row.deleted = True
    elif mutation == "edit":
        row.content = "changed"
        row.revision += 1
    elif mutation == "share":
        row.cloud_providers = '["openrouter"]'
    elif mutation == "expiry":
        row.valid_until = 1
    else:
        db.add(MemorySettings(id=1, enabled=False, revision=1))
    db.commit()
    assert not refresh_memory(db, snapshot)["items"]


def test_provider_projection_requires_exact_explicit_share(db):
    memory(db, label="CLOUD_ALLOWED", cloud_providers='["openrouter"]')
    memory(db, text="Python private")
    snapshot = refresh_memory(db, selected(db))
    assert len(project_memory(snapshot)) == 2
    assert len(project_memory(snapshot, provider_id="openrouter", external=True)) == 1
    assert not project_memory(snapshot, provider_id="anthropic", external=True)


def test_project_scope_and_hidden_knowledge_project(db):
    db.add_all([Project(id="p", name="Apollo"), Project(id="k", name="Secret", kind="knowledge")])
    db.commit()
    good = memory(db, project_id="p")
    memory(db, project_id="k")
    assert not selected(db)["items"]
    assert [r["id"] for r in selected(db, "Apollo Python")["items"]] == [good.id]
    assert not selected(db, "Secret Python")["items"]


def test_byte_budget_is_utf8_and_not_partial_fact(db):
    memory(db, text="Python " + "ä" * 300)
    assert not selected(db, byte_budget=200)["items"]
    snapshot = selected(db, byte_budget=1200)
    assert snapshot["used_bytes"] <= 1200
    assert snapshot["token_estimate"] == snapshot["used_bytes"]


def test_real_hybrid_vector_ranking_and_config_invalidation(db):
    cfg = Settings(
        local_endpoints_json='{"http://localhost:1234/v1":"127.0.0.1"}',
        memory_embedding_base_url="http://localhost:1234/v1",
        memory_embedding_model="synthetic-v1",
    )
    row = memory(db, text="Ich fahre gerne Fahrrad")
    db.add(MemorySettings(id=1, config='{"embedding_enabled":true}'))
    db.commit()
    assert save_embedding(db, cfg, row.id, row.revision, row.sha256, [1.0, 0.0])
    db.commit()
    snapshot = select_memory(
        db, cfg, db.get(Conversation, "chat"), "Welche Hobbys?", query_vector=[1, 0]
    )
    assert [i["id"] for i in snapshot["items"]] == [row.id]
    cached = db.get(MemoryEmbedding, row.id)
    cached.config_sha256 = "different model"
    db.commit()
    assert not select_memory(
        db, cfg, db.get(Conversation, "chat"), "Welche Hobbys?", query_vector=[1, 0]
    )["items"]
    assert configuration(cfg)[1] == "synthetic-v1"


def test_summary_older_extracts_sensitive_exclusion_and_freshness(db):
    for index in range(16):
        content = f"synthetic older decision {index}" if index < 8 else f"LATEST {index}"
        if index == 0:
            content = "Mein Passwort ist synthetic-secret"
        db.add(
            Message(
                id=f"m{index:02}",
                conversation_id="chat",
                role="user" if index % 2 else "assistant",
                content=content,
                created=index,
            )
        )
    db.commit()
    summary = summarize_conversation(db, "chat", byte_budget=1800)
    db.commit()
    assert summary and "LATEST" not in summary.content and "synthetic-secret" not in summary.content
    assert summary.label == "LOCAL_ONLY"
    audit = json.loads(summary.source_snapshot)
    assert audit["recent_excluded"] == 8 and audit["omitted"] >= 1
    assert fresh_summary(db, "chat")
    db.get(Message, "m01").revision += 1
    db.commit()
    assert fresh_summary(db, "chat") is None


def test_short_conversation_no_redundant_summary(db):
    db.add(Message(conversation_id="chat", role="user", content="Hallo"))
    db.commit()
    assert summarize_conversation(db, "chat") is None


def test_structured_predicate_retrieves_without_literal_question_words(db):
    row = memory(db, text="Ich heiße Synthetica", predicate="name")
    assert [item["id"] for item in selected(db, "Was ist mein Name?")["items"]] == [row.id]


def test_full_corpus_rank_precedes_candidate_limit(db):
    target = memory(db, text="Python Beruf", updated=1)
    for index in range(2001):
        db.add(
            Memory(
                content="Python",
                sha256=hashlib.sha256(b"Python").hexdigest(),
                path=f"app/bulk-{index}",
                storage="app",
                category="preference",
            )
        )
    db.commit()
    assert selected(db, "Python Beruf")["items"][0]["id"] == target.id


@pytest.mark.parametrize("mutation", ["inactive", "revision", "content", "archived"])
def test_source_message_change_invalidates_selected_memory(db, mutation):
    source = Message(id="source", conversation_id="chat", role="user", content="Python assertion")
    db.add(source)
    db.commit()
    memory(
        db,
        source_message_id=source.id,
        source_message_revision=source.revision,
        source_sha256=hashlib.sha256(source.content.encode()).hexdigest(),
        source_conversation_id="chat",
    )
    snapshot = selected(db)
    assert snapshot["items"]
    if mutation == "inactive":
        source.active = False
    elif mutation == "revision":
        source.revision += 1
    elif mutation == "content":
        source.content = "edited"
    else:
        db.get(Conversation, "chat").archived = True
    db.commit()
    assert not refresh_memory(db, snapshot)["items"]
    assert not selected(db)["items"]


def test_forgotten_source_never_reappears_in_rebuilt_summary(db):
    for index in range(12):
        db.add(
            Message(
                id=f"s{index:02}",
                conversation_id="chat",
                role="user",
                content=f"synthetic fact {index}",
                created=index,
            )
        )
    db.commit()
    summary = summarize_conversation(db, "chat")
    db.commit()
    assert summary and "synthetic fact 0" in summary.content
    memory(db, text="", status="forgotten", source_message_id="s00", source_conversation_id="chat")
    assert fresh_summary(db, "chat") is None
    rebuilt = summarize_conversation(db, "chat")
    db.commit()
    assert rebuilt and "synthetic fact 0" not in rebuilt.content
    assert "synthetic fact 1" in rebuilt.content
    assert fresh_summary(db, "chat")


@pytest.mark.parametrize("revoke", [False, True])
def test_embedding_worker_backfill_current_revision_and_revocation(db, monkeypatch, revoke):
    row = memory(db)
    db.add(MemorySettings(id=1, config='{"embedding_enabled":true}'))
    db.commit()
    factory = sessionmaker(db.get_bind())
    cfg = Settings(
        local_endpoints_json='{"http://127.0.0.1:9123/v1":"127.0.0.1"}',
        memory_embedding_base_url="http://127.0.0.1:9123/v1",
        memory_embedding_model="synthetic-embedding-v1",
    )

    async def synthetic_embedding(config, content):
        assert content == row.content
        if revoke:
            with factory() as current:
                target = current.get(Memory, row.id)
                target.deleted, target.status = True, "forgotten"
                current.commit()
        return [1.0, 0.0]

    monkeypatch.setattr("hub.memory_embeddings.embed", synthetic_embedding)
    result = asyncio.run(refresh_embeddings(factory, cfg))
    assert result["indexed"] == int(not revoke)
    assert result["stale"] == int(revoke)
    assert bool(db.get(MemoryEmbedding, row.id)) is not revoke


@pytest.mark.parametrize(
    "kind,label",
    [("fact", "Fakt"), ("plan", "Plan"), ("hypothesis", "Hypothese"), ("decision", "Entscheidung")],
)
def test_fact_type_and_validity_visible_and_exact_budget(db, kind, label):
    memory(db, fact_type=kind, confidence=0.91, valid_from=10, valid_until=9999999999)
    snapshot = selected(db)
    parts = project_memory(snapshot)
    assert len(parts) == 1 and f"Typ: {label}" in parts[0].content
    assert "Konfidenz: 0.91" in parts[0].content
    assert "Gültig ab: 10" in parts[0].content
    assert "keine bestätigten Tatsachen" in parts[0].content
    assert snapshot["used_bytes"] == sum(len(p.content.encode()) + 64 for p in parts)
    assert not selected(db, byte_budget=snapshot["used_bytes"] - 1)["items"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("fact_type", "plan"),
        ("confidence", 0.5),
        ("valid_from", 1),
        ("valid_until", 9999999999),
        ("category", "personal"),
    ],
)
def test_metadata_drift_invalidates_snapshot_without_revision_change(db, field, value):
    row = memory(db)
    snapshot = selected(db)
    setattr(row, field, value)
    db.commit()
    assert not refresh_memory(db, snapshot)["items"]


@pytest.mark.parametrize("question", ["Apollo? Python", "Apollo, Python", "(Apollo) Python"])
def test_explicit_whole_project_name_accepts_punctuation(db, question):
    db.add(Project(id="p", name="Apollo"))
    db.commit()
    row = memory(db, project_id="p")
    assert [item["id"] for item in selected(db, question)["items"]] == [row.id]


@pytest.mark.parametrize("question", ["ApolloX Python", "XAPOLLO Python", "Apoll Python"])
def test_partial_or_unknown_project_name_never_adds_scope(db, question):
    db.add(Project(id="p", name="Apollo"))
    db.commit()
    memory(db, project_id="p")
    assert not selected(db, question)["items"]


def test_ambiguous_duplicate_project_names_never_add_scope(db):
    db.add_all([Project(id="p", name="Apollo"), Project(id="q", name="APOLLO")])
    db.commit()
    memory(db, project_id="p")
    memory(db, project_id="q")
    assert not selected(db, "Apollo? Python")["items"]


@pytest.mark.parametrize("category", ["conversation", "knowledge"])
def test_manual_native_note_category_is_retrievable_not_a_hidden_chat_scope(db, category):
    from hub.memory_service import create_app_memory

    row = create_app_memory(db, content="Python synthetic discussion note", category=category)
    db.commit()
    assert [item["id"] for item in selected(db, "Python discussion")["items"]] == [row.id]
    assert not project_memory(
        selected(db, "Python discussion"), external=True, provider_id="openrouter"
    )


def test_ineligible_vault_and_expired_rows_cannot_starve_native_candidate_window(db):
    target = memory(db, text="Python", updated=1)
    for index in range(2001):
        db.add(
            Memory(
                content="Python synthetic",
                sha256=hashlib.sha256(b"Python synthetic").hexdigest(),
                path=f"vault/bulk-{index}",
                storage="vault",
                updated=100,
            )
        )
        db.add(
            Memory(
                content="Python synthetic",
                sha256=hashlib.sha256(b"Python synthetic").hexdigest(),
                path=f"app/expired-{index}",
                storage="app",
                category="personal",
                valid_until=1,
                updated=100,
            )
        )
    db.commit()
    assert [item["id"] for item in selected(db, "Python synthetic")["items"]] == [target.id]
