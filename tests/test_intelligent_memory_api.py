"""Authenticated synthetic API acceptance for native memory and review."""

import uuid

from hub.db import Conversation, Memory, Message
from hub.memory_models import MemoryCandidate
from hub.memory_service import digest

pytest_plugins = ["test_chat"]


def test_settings_auth_cas_validation_and_sensitive_review_cannot_be_disabled(setup):
    _, client, headers, _ = setup
    body = client.get("/api/memory-settings").json()
    assert body["enabled"] and body["extraction_enabled"]
    response = client.put(
        "/api/memory-settings", headers={"Origin": "http://testserver"}, json=body
    )
    assert response.status_code == 403
    body["config"]["sensitive_review_required"] = False
    result = client.put("/api/memory-settings", headers=headers, json=body)
    assert result.status_code == 200 and result.json()["revision"] == 1
    assert result.json()["config"]["sensitive_review_required"]
    assert client.put("/api/memory-settings", headers=headers, json=body).status_code == 409
    bad = result.json()
    bad["config"]["max_memories"] = 10000
    assert client.put("/api/memory-settings", headers=headers, json=bad).status_code == 422
    client.post("/api/logout", headers=headers)
    assert client.get("/api/memory-settings").status_code == 401
    assert client.get("/api/memory-candidates").status_code == 401


def test_native_memory_crud_works_without_vault_and_sharing_is_explicit(setup):
    application, client, headers, _ = setup
    payload = {
        "id": str(uuid.uuid4()),
        "storage": "app",
        "title": "Synthetic native",
        "content": "Synthetic direct saved context",
        "category": "personal",
    }
    response = client.post("/api/memories", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["storage"] == "app" and row["cloud_providers"] == []
    assert row["label"] == "LOCAL_ONLY"
    payload.update(revision=row["revision"], cloud_providers=["openrouter"])
    changed = client.patch("/api/memories/" + row["id"], headers=headers, json=payload)
    assert changed.status_code == 200, changed.text
    assert changed.json()["label"] == "CLOUD_ALLOWED"
    assert (
        client.patch("/api/memories/" + row["id"], headers=headers, json=payload).status_code == 409
    )
    revision = changed.json()["revision"]
    deleted = client.delete(
        "/api/memories/" + row["id"] + "?expected_revision=" + str(revision), headers=headers
    )
    assert deleted.status_code == 200
    assert not any(m["id"] == row["id"] for m in client.get("/api/memories").json())
    with application.state.sessions() as db:
        forgotten = db.get(Memory, row["id"])
        assert forgotten.content == "" and forgotten.status == "forgotten"


def seed(application):
    with application.state.sessions() as db:
        chat = Conversation()
        db.add(chat)
        db.flush()
        message = Message(
            conversation_id=chat.id, role="user", content="Ich habe eine synthetische Diagnose."
        )
        db.add(message)
        db.flush()
        candidate = MemoryCandidate(
            source_message_id=message.id,
            source_message_revision=message.revision,
            source_conversation_id=chat.id,
            source_sha256=digest(message.content),
            quote_start=0,
            quote_end=len(message.content),
            category="personal",
            predicate="health",
            sensitivity="sensitive",
            confidence=0.99,
        )
        db.add(candidate)
        db.commit()
        return candidate.id, message.id


def test_candidate_review_source_preview_and_stale_cas(setup):
    application, client, headers, _ = setup
    identifier, _ = seed(application)
    rows = client.get("/api/memory-candidates").json()
    assert rows[0]["id"] == identifier and rows[0]["fresh"]
    assert rows[0]["preview"] == "Ich habe eine synthetische Diagnose."
    reviewed = client.post(
        "/api/memory-candidates/" + identifier + "/review",
        headers=headers,
        json={"expected_revision": 1, "decision": "approve"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["memory"]["sensitivity"] == "sensitive"
    assert reviewed.json()["memory"]["cloud_providers"] == []
    assert (
        client.post(
            "/api/memory-candidates/" + identifier + "/review",
            headers=headers,
            json={"expected_revision": 1, "decision": "approve"},
        ).status_code
        == 409
    )


def test_stale_source_candidate_cannot_be_approved(setup):
    application, client, headers, _ = setup
    identifier, message_id = seed(application)
    with application.state.sessions() as db:
        db.get(Message, message_id).revision += 1
        db.commit()
    row = client.get("/api/memory-candidates").json()[0]
    assert not row["fresh"] and row["preview"] == ""
    assert (
        client.post(
            "/api/memory-candidates/" + identifier + "/review",
            headers=headers,
            json={"expected_revision": 1, "decision": "approve"},
        ).status_code
        == 409
    )
