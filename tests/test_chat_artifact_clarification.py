"""A missing topic is a bounded conversation turn, never a failed file write."""

import json

import pytest
from hub.chat_artifacts import (
    artifact_clarification,
    clarification_receipt,
    resolved_chat_goal,
)
from hub.db import Artifact, Base, Conversation, Message, Run
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.mark.parametrize(
    ("goal", "snippet"),
    [
        ("Bitte erstelle eine Powerpoint Präsentation mit 5 Folien", "5 Folien"),
        ("Erstelle mir eine Word-Datei.", "Word-Dokument"),
        ("Create a PDF document.", "PDF-Dokument"),
    ],
)
def test_format_without_content_asks_for_topic(goal, snippet):
    assert snippet in artifact_clarification(goal)


@pytest.mark.parametrize(
    "goal",
    [
        "Erstelle eine Präsentation über Managed Services mit 5 Folien.",
        "Erstelle daraus eine Word-Datei.",
        "Erstelle aus Projektunterlagen eine Word-Datei.",
        "Kürze die letzte PowerPoint-Präsentation.",
        "Erstelle Word und PDF.",
        "Wie erstellt man eine Präsentation?",
    ],
)
def test_content_revisions_and_ambiguous_formats_are_not_empty_requests(goal):
    assert artifact_clarification(goal) is None


@pytest.mark.parametrize("drift", [None, "origin", "reply", "failed", "interrupted", "inactive"])
def test_pending_request_is_bound_to_exact_immediate_active_turn(drift):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        chat = Conversation()
        db.add(chat)
        db.flush()
        origin = Message(
            conversation_id=chat.id,
            role="user",
            content="Bitte erstelle eine Powerpoint Präsentation mit 5 Folien",
            created=1,
        )
        db.add(origin)
        db.flush()
        question = artifact_clarification(origin.content)
        run = Run(
            conversation_id=chat.id,
            status="succeeded",
            context_snapshot=json.dumps(
                {"artifact_clarification": clarification_receipt(origin, question)}
            ),
        )
        db.add(run)
        db.flush()
        reply = Message(
            conversation_id=chat.id, role="assistant", content=question, run_id=run.id, created=2
        )
        latest = Message(
            conversation_id=chat.id,
            role="user",
            content="Managed Services für Führungskräfte",
            created=4,
        )
        db.add_all([reply, latest])
        if drift == "origin":
            origin.revision += 1
        elif drift == "reply":
            reply.content += " Changed"
        elif drift == "failed":
            run.status = "failed"
        elif drift == "interrupted":
            db.add(Message(conversation_id=chat.id, role="user", content="Hallo", created=3))
        elif drift == "inactive":
            origin.active = False
        db.flush()
        resolved = resolved_chat_goal(db, chat, latest)
        if drift:
            assert resolved == latest.content
        else:
            assert "5 Folien" in resolved and latest.content in resolved
        assert db.query(Artifact).count() == 0


@pytest.mark.parametrize("reply", ["Abbrechen", "Bitte erstelle eine Word-Datei über Wasser."])
def test_new_instruction_does_not_reuse_old_pending_request(reply):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        chat = Conversation()
        db.add(chat)
        db.flush()
        origin = Message(
            conversation_id=chat.id, role="user", content="Erstelle PowerPoint.", created=1
        )
        db.add(origin)
        db.flush()
        question = artifact_clarification(origin.content)
        run = Run(
            conversation_id=chat.id,
            status="succeeded",
            context_snapshot=json.dumps(
                {"artifact_clarification": clarification_receipt(origin, question)}
            ),
        )
        db.add(run)
        db.flush()
        db.add(
            Message(
                conversation_id=chat.id,
                role="assistant",
                content=question,
                run_id=run.id,
                created=2,
            )
        )
        latest = Message(conversation_id=chat.id, role="user", content=reply, created=3)
        db.add(latest)
        db.flush()
        assert resolved_chat_goal(db, chat, latest) == reply


@pytest.fixture
def api_setup(tmp_path, monkeypatch):
    import test_artifact_api

    yield from test_artifact_api.setup.__wrapped__(tmp_path, monkeypatch)


def test_normal_chat_clarification_then_exact_five_slide_file(api_setup):
    import test_chat_artifacts

    app, c, h, cfg, pid, _ = api_setup
    presentation = json.dumps(
        {
            "title": "Synthetische Präsentation",
            "slides": [
                {"title": f"Folie {i}", "bullets": ["Synthetischer Inhalt"]} for i in range(5)
            ],
        }
    )

    class CountingProvider(test_chat_artifacts.FileProvider):
        route_calls = 0

        async def route(self, parts, roles):
            self.route_calls += 1
            return await super().route(parts, roles)

    provider = CountingProvider(presentation)
    app.state.providers = provider
    chat = c.post("/api/conversations", headers=h, json={}).json()["id"]
    first = c.post(
        f"/api/conversations/{chat}/messages",
        headers=h,
        json={"content": "Bitte erstelle eine Powerpoint Präsentation mit 5 Folien"},
    )
    assert "succeeded" in first.text and "Zu welchem Thema" in first.text
    assert provider.calls == 0 and provider.route_calls == 0
    assert c.get(f"/api/conversations/{chat}/artifacts").json() == []
    second = c.post(
        f"/api/conversations/{chat}/messages",
        headers=h,
        json={"content": "Managed Services für Führungskräfte"},
    )
    assert "succeeded" in second.text, second.text
    assert provider.calls == 1
    assert any("5 Folien" in part.content for part in provider.parts)
    assert any("Managed Services" in part.content for part in provider.parts)
    row = c.get(f"/api/conversations/{chat}/artifacts").json()[0]
    assert row["project_id"] is None and row["conversation_id"] == chat
    assert len(row["spec"]["plan"]["slides"]) == 5
    assert row["draft"]["provider"]["kind"] == "local"
    receipt = c.get(f"/api/conversations/{chat}").json()["runs"][-1]["artifact"]
    assert receipt["conversation_id"] == chat and receipt["project_id"] is None
    assert (
        c.get(
            f"/api/conversations/{chat}/artifacts/{row['artifact_id']}/versions/1/download"
        ).status_code
        == 409
    )
    assert c.get(f"/api/projects/{pid}/artifacts").json() == []


def test_normal_chat_word_and_followup_revision_keep_exact_scope(api_setup):
    import test_chat_artifacts

    app, c, h, cfg, pid, _ = api_setup
    provider = test_chat_artifacts.FileProvider(test_chat_artifacts.DOCUMENT)
    app.state.providers = provider
    chat = c.post("/api/conversations", headers=h, json={}).json()["id"]
    first = c.post(
        f"/api/conversations/{chat}/messages",
        headers=h,
        json={"content": "Erstelle eine Word-Datei über synthetische Daten mit einem Abschnitt."},
    )
    assert "succeeded" in first.text, first.text
    row = c.get(f"/api/conversations/{chat}/artifacts").json()[0]
    provider.output = test_chat_artifacts.DOCUMENT.replace("Synthetische Daten.", "Kurz.")
    second = c.post(
        f"/api/conversations/{chat}/messages",
        headers=h,
        json={"content": "Kürze die letzte Word-Datei auf einen Abschnitt."},
    )
    assert "succeeded" in second.text, second.text
    rows = c.get(f"/api/conversations/{chat}/artifacts").json()
    assert sorted(item["revision"] for item in rows) == [1, 2]
    assert {item["artifact_id"] for item in rows} == {row["artifact_id"]}
    assert all(item["conversation_id"] == chat and item["project_id"] is None for item in rows)
    assert c.get(f"/api/projects/{pid}/artifacts").json() == []


@pytest.mark.parametrize("drift", ["origin_revision", "origin_content", "reply_content"])
def test_clarification_binding_rechecked_after_model_generation(api_setup, drift):
    import test_chat_artifacts
    from sqlalchemy import select

    app, c, h, cfg, pid, _ = api_setup
    chat = c.post("/api/conversations", headers=h, json={}).json()["id"]
    first = c.post(
        f"/api/conversations/{chat}/messages",
        headers=h,
        json={"content": "Erstelle eine Word-Datei."},
    )
    assert "succeeded" in first.text

    def change():
        with app.state.sessions() as db:
            messages = list(
                db.scalars(
                    select(Message)
                    .where(Message.conversation_id == chat)
                    .order_by(Message.created, Message.id)
                )
            )
            if drift == "origin_revision":
                messages[0].revision += 1
            elif drift == "origin_content":
                messages[0].content = "Changed"
            else:
                messages[1].content = "Changed"
            db.commit()

    app.state.providers = test_chat_artifacts.FileProvider(test_chat_artifacts.DOCUMENT, change)
    second = c.post(
        f"/api/conversations/{chat}/messages",
        headers=h,
        json={"content": "Über synthetische Managed Services"},
    )
    assert "failed" in second.text and "succeeded" not in second.text
    assert c.get(f"/api/conversations/{chat}/artifacts").json() == []
