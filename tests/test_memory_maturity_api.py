"""Authenticated review, explicit promotion and bounded pointer-only learning retries."""

import json

from hub.db import Conversation, Message, Run
from hub.memory_learning import reserve_learning
from hub.memory_models import MemoryCandidate, MemoryLearningJob
from hub.memory_service import SourcePointer, create_app_memory, digest

pytest_plugins = ["test_chat"]


def seed(application, *, predicate="preference"):
    with application.state.sessions() as db:
        chat = Conversation()
        db.add(chat)
        db.flush()
        run = Run(conversation_id=chat.id, status="succeeded")
        db.add(run)
        db.flush()
        message = Message(
            conversation_id=chat.id,
            run_id=run.id,
            role="user",
            content="Ich bevorzuge SyntheticAPIStyle",
        )
        db.add(message)
        db.commit()
        return chat.id, run.id, message.id


def test_learning_status_and_retry_are_authenticated_source_bound_and_not_private_quote_exports(
    setup,
):
    application, client, headers, cfg = setup
    chat, run_id, message_id = seed(application)
    with application.state.sessions() as db:
        identifier = reserve_learning(db, cfg, run_id)
        row = db.get(MemoryLearningJob, identifier)
        row.status, row.error = "failed", "local_extraction_unavailable"
        db.commit()
    listing = client.get("/api/memory-learning-jobs")
    assert listing.status_code == 200
    item = next(row for row in listing.json() if row["id"] == identifier)
    assert item["current"] and item["retryable"] and item["attempts"] == 1
    assert "SyntheticAPIStyle" not in json.dumps(item)
    path = f"/api/memory-learning-jobs/{identifier}/retry"
    assert (
        client.post(
            path, json={"expected_attempts": 1}, headers={"Origin": "http://testserver"}
        ).status_code
        == 403
    )
    retried = client.post(path, json={"expected_attempts": 1}, headers=headers)
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert retried.json()["attempts"] == 2
    assert client.post(path, json={"expected_attempts": 1}, headers=headers).status_code == 409
    with application.state.sessions() as db:
        db.get(MemoryLearningJob, identifier).status = "failed"
        db.get(Message, message_id).revision += 1
        db.commit()
    assert client.post(path, json={"expected_attempts": 2}, headers=headers).status_code == 409
    client.post("/api/logout", headers=headers)
    assert client.get("/api/memory-learning-jobs").status_code == 401


def test_archived_memory_visibility_and_explicit_promotion_clear_cloud_grants(setup):
    application, client, headers, cfg = setup
    chat, _, message_id = seed(application)
    with application.state.sessions() as db:
        message = db.get(Message, message_id)
        row = create_app_memory(
            db,
            content=message.content,
            cloud_providers=["openrouter"],
            source=SourcePointer(message.id, message.revision, chat, digest(message.content)),
        )
        db.get(Conversation, chat).archived = True
        db.commit()
        identifier, revision = row.id, row.revision
    before = client.get(f"/api/memories/{identifier}").json()
    assert before["provenance_status"] == "archived_origin" and before["can_promote"]
    assert before["context_eligible"] is False
    promoted = client.post(
        f"/api/memories/{identifier}/promote", headers=headers, json={"expected_revision": revision}
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["provenance_status"] == "independent"
    assert promoted.json()["cloud_providers"] == [] and promoted.json()["label"] == "LOCAL_ONLY"
    assert (
        client.post(
            f"/api/memories/{identifier}/promote",
            headers=headers,
            json={"expected_revision": revision},
        ).status_code
        == 409
    )


def test_candidate_replace_requires_explicit_compatible_current_target(setup):
    application, client, headers, cfg = setup
    chat, _, message_id = seed(application)
    with application.state.sessions() as db:
        old = create_app_memory(db, content="Ich arbeite als Ingenieur", predicate="profession")
        message = db.get(Message, message_id)
        message.content = "Ich arbeite als Lehrer"
        candidate = MemoryCandidate(
            source_message_id=message.id,
            source_message_revision=message.revision,
            source_conversation_id=chat,
            source_sha256=digest(message.content),
            quote_start=0,
            quote_end=len(message.content),
            predicate="profession",
            subject="user",
        )
        db.add(candidate)
        db.commit()
        identifier, old_id, old_revision = candidate.id, old.id, old.revision
    pending = next(
        row for row in client.get("/api/memory-candidates").json() if row["id"] == identifier
    )
    assert pending["replacement_options"][0]["id"] == old_id
    path = f"/api/memory-candidates/{identifier}/review"
    assert (
        client.post(
            path, headers=headers, json={"expected_revision": 1, "decision": "approve"}
        ).status_code
        == 409
    )
    response = client.post(
        path,
        headers=headers,
        json={
            "expected_revision": 1,
            "decision": "approve",
            "replacement_memory_id": old_id,
            "replacement_revision": old_revision,
        },
    )
    assert response.status_code == 200, response.text
