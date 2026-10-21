"""Synthetic lifecycle and source-privacy acceptance; no services or user data."""

import asyncio
import json

import pytest
from hub.config import Settings
from hub.db import Base, Conversation, Memory, MemoryRevision, Message, Project, Run
from hub.memory_embeddings import MemoryEmbedding
from hub.memory_learning import Extraction, apply_extraction, execute_learning, reserve_learning
from hub.memory_models import MemoryCandidate, MemoryLearningJob, MemorySettings
from hub.memory_service import (
    SourcePointer,
    candidate_quote,
    create_app_memory,
    digest,
    edit_app_memory,
    forget_memory,
    fresh_source,
    memory_info,
    review_candidate,
)
from hub.memory_settings import candidate_info, get_settings
from hub.memory_summary import ConversationSummary
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def factory():
    assert ConversationSummary.__tablename__ == "conversation_summaries"
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def source(db, text="Ich arbeite als Ingenieur."):
    chat = Conversation()
    db.add(chat)
    db.flush()
    run = Run(conversation_id=chat.id, status="succeeded")
    db.add(run)
    db.flush()
    msg = Message(conversation_id=chat.id, run_id=run.id, role="user", content=text)
    db.add(msg)
    db.flush()
    return msg, run


def extract(quote, predicate="profession", **kw):
    return Extraction.model_validate(
        {"facts": [{"quote": quote, "predicate": predicate, "confidence": 0.99, **kw}]}
    )


def apply(db, text="Ich arbeite als Ingenieur.", predicate="profession", **kw):
    message, run = source(db, text)
    job_id = reserve_learning(db, Settings(), run.id)
    job = db.get(MemoryLearningJob, job_id)
    assert job
    apply_extraction(db, job, extract(text, predicate, **kw))
    db.flush()
    return message, run, job


def test_native_without_vault_and_model_independent(factory):
    with factory() as db:
        row = create_app_memory(db, title="Synthetic", content="A directly saved fact")
        db.commit()
        assert row.storage == "app" and row.label == "LOCAL_ONLY"
        assert memory_info(row)["cloud_providers"] == []
        assert row.source_sha256 == ""
        assert db.get(MemoryRevision, (row.id, 1)).content == row.content


def test_duplicate_and_explicit_correction_preserve_history(factory):
    with factory() as db:
        old = create_app_memory(db, content="Ich bin Ingenieur.", predicate="profession")
        same = create_app_memory(db, content="Ich bin Ingenieur.", predicate="profession")
        assert same.id == old.id
        with pytest.raises(ValueError, match="Widersprüchlicher"):
            create_app_memory(db, content="Ich bin Lehrer.", predicate="profession")
        new = create_app_memory(
            db, content="Ich bin Lehrer.", predicate="profession", explicit_correction=True
        )
        assert old.status == "superseded" and new.supersedes_id == old.id
        assert db.get(MemoryRevision, (old.id, 1)).content == "Ich bin Ingenieur."


def test_fresh_source_fails_after_edit_archive_inactive_or_role_change(factory):
    with factory() as db:
        message, _ = source(db)
        pointer = SourcePointer(
            message.id, message.revision, message.conversation_id, digest(message.content)
        )
        assert fresh_source(db, pointer) is message
        message.content = "Ich arbeite inzwischen als Lehrer."
        with pytest.raises(ValueError):
            fresh_source(db, pointer)


@pytest.mark.parametrize("change", ["role", "active", "archive", "revision", "conversation"])
def test_source_revocation_variants(factory, change):
    with factory() as db:
        message, _ = source(db)
        pointer = SourcePointer(
            message.id, message.revision, message.conversation_id, digest(message.content)
        )
        if change == "role":
            message.role = "assistant"
        elif change == "active":
            message.active = False
        elif change == "archive":
            db.get(Conversation, message.conversation_id).archived = True
        elif change == "revision":
            message.revision += 1
        else:
            message.conversation_id = "other"
        with pytest.raises(ValueError):
            fresh_source(db, pointer)


def test_sensitive_pending_never_copies_content_and_approval_reconstructs(factory):
    text = "Ich habe eine synthetische Diagnose."
    with factory() as db:
        message, _, _ = apply(db, text, predicate="health", sensitive=False)
        assert list(db.scalars(select(Memory))) == []
        candidate = db.scalar(select(MemoryCandidate))
        values = {
            column.name: getattr(candidate, column.name)
            for column in MemoryCandidate.__table__.columns
        }
        assert text not in json.dumps(values)
        assert candidate_quote(db, candidate) == text
        assert candidate.sensitivity == "sensitive"
        row = review_candidate(db, candidate.id, approve=True, expected_revision=1)
        assert row.content == text and row.cloud_providers == "[]"
        assert row.source_message_id == message.id
        assert candidate.status == "approved"
        with pytest.raises(ValueError):
            review_candidate(db, candidate.id, approve=True, expected_revision=1)


def test_stale_sensitive_proposal_cannot_reconstruct_or_approve(factory):
    with factory() as db:
        message, _, _ = apply(db, "Ich habe eine synthetische Diagnose.", "health")
        candidate = db.scalar(select(MemoryCandidate))
        message.revision += 1
        assert candidate_info(db, candidate)["preview"] == ""
        assert not candidate_info(db, candidate)["fresh"]
        with pytest.raises(ValueError):
            review_candidate(db, candidate.id, approve=True, expected_revision=1)
        assert list(db.scalars(select(Memory))) == []


def test_reject_preserves_no_sensitive_memory(factory):
    with factory() as db:
        apply(db, "Ich habe eine synthetische Diagnose.", "health")
        candidate = db.scalar(select(MemoryCandidate))
        assert review_candidate(db, candidate.id, approve=False, expected_revision=1) is None
        assert candidate.status == "rejected"
        assert list(db.scalars(select(Memory))) == []


@pytest.mark.parametrize(
    "quote",
    [
        "He is a lawyer.",
        "Ich bin Millionär.",
        "Ich arbeite als Ingenieur?",
        "Ich habe ein Passwort abc.",
    ],
)
def test_model_inferences_questions_credentials_not_accepted(factory, quote):
    with factory() as db:
        msg, run = source(db)
        job = db.get(MemoryLearningJob, reserve_learning(db, Settings(), run.id))
        apply_extraction(db, job, extract(quote))
        assert list(db.scalars(select(MemoryCandidate))) == []
        assert list(db.scalars(select(Memory))) == []


def test_low_confidence_not_persisted_and_plan_not_promoted_to_fact(factory):
    with factory() as db:
        apply(db, "Ich plane ein synthetisches Studium.", "plan", fact_type="fact")
        row = db.scalar(select(Memory))
        assert row.fact_type == "plan"


def test_review_required_stores_only_pointer(factory):
    with factory() as db:
        db.add(MemorySettings(id=1, config='{"review_required":true}'))
        apply(db)
        assert db.scalar(select(Memory)) is None
        assert db.scalar(select(MemoryCandidate)).status == "pending"


def test_conflict_requires_review_instead_of_two_active_values(factory):
    with factory() as db:
        apply(db)
        apply(db, "Ich arbeite als Lehrer.")
        active = list(db.scalars(select(Memory).where(Memory.status == "active")))
        assert len(active) == 1 and active[0].content == "Ich arbeite als Ingenieur."
        assert (
            len(
                list(db.scalars(select(MemoryCandidate).where(MemoryCandidate.status == "pending")))
            )
            == 1
        )


def test_settings_revision_change_revokes_pending_learning(factory):
    with factory() as db:
        message, run = source(db)
        job = db.get(MemoryLearningJob, reserve_learning(db, Settings(), run.id))
        db.add(MemorySettings(id=1, revision=1, enabled=False))
        with pytest.raises(ValueError):
            apply_extraction(db, job, extract(message.content))
        assert db.scalar(select(Memory)) is None


def test_forget_redacts_revisions_vectors_and_blocks_old_source_relearning(factory):
    with factory() as db:
        message, run, _ = apply(db)
        row = db.scalar(select(Memory))
        db.add(
            MemoryEmbedding(
                memory_id=row.id,
                revision=row.revision,
                sha256=row.sha256,
                model="synthetic",
                config_sha256="a" * 64,
                dimensions=1,
                vector="[1]",
            )
        )
        db.flush()
        forget_memory(db, row, expected_revision=1)
        db.flush()
        assert row.content == "" and row.base_content == "" and row.status == "forgotten"
        assert db.get(MemoryEmbedding, row.id) is None
        assert (
            list(db.scalars(select(MemoryRevision).where(MemoryRevision.memory_id == row.id))) == []
        )
        assert message.content != "" and reserve_learning(db, Settings(), run.id) is None


def test_edit_cas_and_source_reset(factory):
    with factory() as db:
        apply(db)
        row = db.scalar(select(Memory))
        with pytest.raises(ValueError):
            edit_app_memory(db, row, expected_revision=999, content="Changed")
        edit_app_memory(db, row, expected_revision=1, content="Changed", cloud_providers=[])
        assert row.revision == 2 and row.source_message_id is None and row.source_sha256 == ""
        assert db.get(MemoryRevision, (row.id, 1)).content == "Ich arbeite als Ingenieur."


def test_executor_local_only_once_and_fixed_telemetry(factory):
    class Fake:
        calls = 0

        async def stream(self, parts, roles, *, external, grants):
            assert external is False and grants == []
            assert all(part.label.value == "LOCAL_ONLY" for part in parts)
            self.calls += 1
            yield json.dumps(
                {
                    "facts": [
                        {
                            "quote": "Ich arbeite bei einer Firma.",
                            "predicate": "profession",
                            "confidence": 0.99,
                        }
                    ]
                }
            )

    with factory() as db:
        _, run = source(db, "Ich arbeite bei einer Firma.")
        identifier = reserve_learning(db, Settings(), run.id)
        db.commit()
    fake = Fake()
    asyncio.run(execute_learning(factory, Settings(), identifier, fake))
    asyncio.run(execute_learning(factory, Settings(), identifier, fake))
    with factory() as db:
        assert db.get(MemoryLearningJob, identifier).status == "succeeded"
        assert fake.calls == 1 and len(list(db.scalars(select(Memory)))) == 1


def test_missing_local_provider_degrades_without_fake_fact(factory):
    with factory() as db:
        _, run = source(db, "Ich arbeite bei einer Firma.")
        identifier = reserve_learning(db, Settings(), run.id)
        db.commit()
    asyncio.run(execute_learning(factory, Settings(), identifier))
    with factory() as db:
        job = db.get(MemoryLearningJob, identifier)
        assert job.status == "failed" and job.error == "local_extraction_unavailable"
        assert not list(db.scalars(select(Memory)))
        assert get_settings(db)["enabled"]


@pytest.mark.parametrize("prefix", ["Beispiel: ", "Angenommen: ", "> ", "```text\n"])
def test_pasted_or_hypothetical_self_assertion_not_learned(factory, prefix):
    quote = "Ich arbeite als Ingenieur."
    with factory() as db:
        message, run = source(db, prefix + quote)
        assert reserve_learning(db, Settings(), run.id) is None
        assert db.scalar(select(MemoryCandidate)) is None


def test_frozen_source_uses_admitted_message_not_latest_followup(factory):
    with factory() as db:
        message, run = source(db)
        message.run_id = None  # Real API stores the request message through its run snapshot.
        run.context_snapshot = json.dumps(
            {
                "memory_source": {
                    "id": message.id,
                    "revision": message.revision,
                    "sha256": digest(message.content),
                }
            }
        )
        db.add(
            Message(conversation_id=message.conversation_id, role="user", content="NEW FOLLOWUP")
        )
        job_id = reserve_learning(db, Settings(), run.id)
        assert db.get(MemoryLearningJob, job_id).source_message_id == message.id


def test_forget_cannot_be_reversed_by_pending_candidate_approval(factory):
    with factory() as db:
        message, run, job = apply(db)
        row = db.scalar(select(Memory))
        pending = MemoryCandidate(
            source_message_id=message.id,
            source_message_revision=message.revision,
            source_conversation_id=message.conversation_id,
            source_sha256=digest(message.content),
            quote_start=0,
            quote_end=len(message.content),
            predicate="other",
            category="personal",
        )
        db.add(pending)
        db.flush()
        forget_memory(db, row, expected_revision=row.revision)
        with pytest.raises(ValueError, match="vergessen"):
            review_candidate(db, pending.id, approve=True, expected_revision=1)
        assert candidate_info(db, pending)["preview"] == ""


def test_explicit_cloud_sharing_revoked_per_revision(factory):
    with factory() as db:
        row = create_app_memory(db, content="Synthetic share", cloud_providers=["openrouter"])
        assert row.label == "CLOUD_ALLOWED"
        edit_app_memory(db, row, expected_revision=1, content="Synthetic share", cloud_providers=[])
        assert row.label == "LOCAL_ONLY" and row.cloud_providers == "[]"


def test_project_assertion_is_scoped_and_decision_keeps_its_type(factory):
    quote = "Wir haben beschlossen, im Projekt SQLite zu nutzen."
    with factory() as db:
        project = Project(name="Synthetic project")
        db.add(project)
        db.flush()
        message, run = source(db, quote)
        db.get(Conversation, message.conversation_id).project_id = project.id
        job = db.get(MemoryLearningJob, reserve_learning(db, Settings(), run.id))
        apply_extraction(db, job, extract(quote, "decision", fact_type="decision"))
        row = db.scalar(select(Memory))
        assert row.category == "project" and row.project_id == project.id
        assert row.fact_type == "decision" and row.label == "LOCAL_ONLY"


def test_remember_request_keeps_exact_quote_not_instruction(factory):
    quote = "ich arbeite als Ingenieur."
    with factory() as db:
        message, run = source(db, "Merke dir bitte, dass " + quote)
        job = db.get(MemoryLearningJob, reserve_learning(db, Settings(), run.id))
        apply_extraction(db, job, extract(quote))
        assert db.scalar(select(Memory)).content == quote


def test_background_post_dispatch_revocation_keeps_no_facts(factory):
    class RevokingProvider:
        async def stream(self, *args, **kwargs):
            with factory() as db:
                db.add(MemorySettings(id=1, revision=1, enabled=False))
                db.commit()
            yield json.dumps(
                {
                    "facts": [
                        {
                            "quote": "Ich arbeite bei einer Firma.",
                            "predicate": "profession",
                            "confidence": 0.99,
                        }
                    ]
                }
            )

    with factory() as db:
        _, run = source(db, "Ich arbeite bei einer Firma.")
        identifier = reserve_learning(db, Settings(), run.id)
        db.commit()
    asyncio.run(execute_learning(factory, Settings(), identifier, RevokingProvider()))
    with factory() as db:
        assert db.get(MemoryLearningJob, identifier).status == "failed"
        assert db.scalar(select(Memory)) is None and db.scalar(select(MemoryCandidate)) is None


@pytest.mark.parametrize(
    "text",
    [
        "Hi",
        "Was ist Photosynthese?",
        "Welche Mails gab es heute?",
        "Ich möchte wissen, wie PostgreSQL funktioniert.",
        "Ich will, dass du eine Mail suchst.",
        "Ich bin heute verantwortlich?",
        "Mein Name?",
        "I want to know how SQL works.",
        "Ich möchte verstehen, wie Routing funktioniert.",
    ],
)
def test_normal_questions_and_assistant_requests_create_no_learning_job(factory, text):
    with factory() as db:
        _, run = source(db, text)
        assert reserve_learning(db, Settings(), run.id) is None
        assert db.scalar(select(MemoryLearningJob)) is None


@pytest.mark.parametrize(
    "text",
    [
        "Ich bin Ingenieur.",
        "Ich plane ein Studium.",
        "Ich bevorzuge kurze Antworten.",
        "Mein Name ist Synthetic.",
        "Merke dir bitte, dass ich in einer Teststadt wohne.",
        "Ich arbeite als Ingenieur. Kannst du mir beruflich helfen?",
    ],
)
def test_direct_statements_still_admit_local_learning(factory, text):
    with factory() as db:
        _, run = source(db, text)
        assert reserve_learning(db, Settings(), run.id)


@pytest.mark.parametrize("kind", ["plan", "hypothesis"])
def test_future_or_uncertain_value_never_supersedes_established_fact(factory, kind):
    with factory() as db:
        fact = create_app_memory(db, content="Ich bin Ingenieur.", predicate="profession")
        uncertain = create_app_memory(
            db,
            content="Ich werde jetzt Lehrer.",
            predicate="profession",
            fact_type=kind,
            explicit_correction=True,
        )
        assert fact.status == "active" and uncertain.status == "active"
        assert uncertain.supersedes_id is None


@pytest.mark.parametrize(
    "change", [{"cloud_providers": []}, {"sensitivity": "sensitive"}, {"fact_type": "hypothesis"}]
)
def test_duplicate_text_cannot_inherit_or_silently_ignore_sharing_changes(factory, change):
    with factory() as db:
        row = create_app_memory(db, content="Synthetic dupe", cloud_providers=["openrouter"])
        kwargs = {"content": "Synthetic dupe", "cloud_providers": ["openrouter"], **change}
        with pytest.raises(ValueError, match="aktueller Revision"):
            create_app_memory(db, **kwargs)
        assert row.label == "CLOUD_ALLOWED" and row.cloud_providers == '["openrouter"]'


def test_identity_cached_source_revocation_is_reloaded(factory):
    with factory() as db:
        message, _ = source(db)
        db.commit()
        pointer = SourcePointer(
            message.id, message.revision, message.conversation_id, digest(message.content)
        )
        with factory() as other:
            other.get(Message, message.id).active = False
            other.commit()
        assert message.active  # The first session still holds the formerly valid object.
        with pytest.raises(ValueError):
            fresh_source(db, pointer)


def test_identity_cached_run_cancellation_is_reloaded_after_lock(factory):
    with factory() as db:
        message, run = source(db)
        job = db.get(MemoryLearningJob, reserve_learning(db, Settings(), run.id))
        db.commit()
        with factory() as other:
            other.get(Run, run.id).cancel_requested = True
            other.commit()
        assert not run.cancel_requested
        with pytest.raises(ValueError):
            apply_extraction(db, job, extract(message.content))
        assert db.scalar(select(Memory)) is None


def test_identity_cached_settings_revocation_is_reloaded(factory):
    with factory() as db:
        original = MemorySettings(id=1)
        db.add(original)
        db.commit()
        assert get_settings(db)["enabled"]
        with factory() as other:
            other.get(MemorySettings, 1).enabled = False
            other.commit()
        assert original.enabled
        assert not get_settings(db)["enabled"]


def test_missing_result_collection_is_failure_not_silent_success(factory):
    with factory() as db:
        _, run = source(db, "Ich arbeite bei einer Firma.")
        job_id = reserve_learning(db, Settings(), run.id)
        db.commit()

    class EmptyObject:
        async def stream(self, *args, **kwargs):
            yield "{}"

    asyncio.run(execute_learning(factory, Settings(), job_id, EmptyObject()))
    with factory() as db:
        job = db.get(MemoryLearningJob, job_id)
        assert job.status == "failed" and job.error == "local_extraction_unavailable"
        assert db.scalar(select(Memory)) is None
