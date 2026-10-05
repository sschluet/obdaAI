import json

import pytest
import test_artifact_api
from hub.chat_artifacts import request_format, requests_project_sources
from hub.db import ArtifactRevision, Message, Run, Source, SourceChunk
from hub.routing import Route
from sqlalchemy import func, select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_artifact_api.setup.__wrapped__(tmp_path, monkeypatch)


class FileProvider:
    def __init__(self, output, effect=None):
        self.output, self.effect, self.calls = output, effect, 0

    async def route(self, parts, roles):
        return Route(capabilities=["artifact"], model_class="cloud", reason="Explicit local file")

    async def title(self, parts, roles):
        return "Synthetic file chat"

    async def stream(self, parts, roles, *, external, grants):
        assert not external and not grants and 2 <= len(parts) <= 10
        self.parts = parts
        self.calls += 1
        if self.effect:
            self.effect()
        yield self.output


DOCUMENT = (
    '{"title":"Lokaler Chatbericht","sections":[{'
    '"heading":"Ergebnis","paragraphs":["Synthetische Daten."]}]}'
)


def test_chat_file_uses_same_review_gate_and_links_exact_request(setup):
    app, c, h, cfg, pid, _ = setup
    provider = FileProvider(DOCUMENT)
    app.state.providers = provider
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    response = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle eine Word-Datei über synthetische Daten."},
    )
    assert response.status_code == 200 and "succeeded" in response.text, response.text
    assert "artifact" in response.text and provider.calls == 1
    detail = c.get("/api/conversations/" + chat).json()
    receipt = detail["runs"][0]["artifact"]
    assert receipt["project_id"] == pid and receipt["sources"] == []
    assert receipt["label"] == "LOCAL_ONLY" and receipt["requires_review"]
    rows = c.get("/api/projects/" + pid + "/artifacts").json()
    row = rows[0]
    assert row["artifact_id"] == receipt["artifact_id"] and row["revision"] == 1
    assert row["draft"]["provider"]["kind"] == "local"
    assert c.get(test_artifact_api.base(pid, row) + "/download").status_code == 409
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ArtifactRevision)) == 1
        run = db.scalar(select(Run))
        message = db.get(Message, receipt["message_id"])
        assert message.active and message.revision == receipt["message_revision"]
        assert run.cost is None and run.provider == "local"
        assert run.first_content_seconds is not None


@pytest.mark.parametrize("drift", [False, True])
def test_explicit_project_documents_are_bound_locally_and_rechecked(setup, drift):
    app, c, h, cfg, pid, spec = setup
    source_id = spec["sources"][0]["id"]
    foreign = c.post("/api/projects", headers=h, json={"name": "Foreign evidence"}).json()["id"]
    with app.state.sessions() as db:
        db.add(
            SourceChunk(source_id=source_id, locator="Synthetic page 1", content="Blue evidence.")
        )
        other = Source(
            project_id=foreign,
            name="Foreign private document",
            sha256="b" * 64,
            size=1,
            status="ready",
        )
        db.add(other)
        db.flush()
        db.add(
            SourceChunk(
                source_id=other.id, locator="Private", content="Never include foreign text."
            )
        )
        db.commit()

    def change():
        if drift:
            with app.state.sessions() as db:
                db.get(Source, source_id).revision += 1
                db.commit()

    provider = FileProvider(DOCUMENT, change)
    app.state.providers = provider
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    response = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle aus den Projektunterlagen eine Word-Datei mit einem Abschnitt."},
    )
    assert provider.calls == 1
    assert any("Blue evidence." in part.content for part in provider.parts)
    assert all("Never include foreign text." not in part.content for part in provider.parts)
    rows = c.get("/api/projects/" + pid + "/artifacts").json()
    if drift:
        assert "succeeded" not in response.text and not rows
    else:
        assert "succeeded" in response.text
        assert rows[0]["spec"]["sources"] == spec["sources"]
        assert rows[0]["draft"]["citations"][0]["source_id"] == source_id
        detail = c.get("/api/conversations/" + chat).json()
        assert detail["runs"][0]["artifact"]["sources"] == spec["sources"]


def test_project_document_selection_is_explicit_and_conflicts_are_rejected():
    assert requests_project_sources("Erstelle aus den Projektunterlagen eine Präsentation.")
    assert not requests_project_sources("Erstelle ohne Projektunterlagen eine Word-Datei.")
    assert not requests_project_sources("Erstelle eine Word-Datei.")
    with pytest.raises(ValueError, match="widersprüchlich"):
        requests_project_sources(
            "Erstelle aus Projektunterlagen Word, aber ohne Projektunterlagen."
        )


def test_invalid_model_plan_records_bounded_failure_and_creates_no_file(setup):
    app, c, h, cfg, pid, _ = setup
    invalid = json.loads(DOCUMENT)
    invalid["title"] = "X" * 1000
    app.state.providers = FileProvider(json.dumps(invalid))
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    response = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle eine Word-Datei."},
    )
    assert "failed" in response.text and "succeeded" not in response.text
    with app.state.sessions() as db:
        run = db.scalar(select(Run))
        assert run.status == "failed" and run.finished is not None
        assert run.error and len(run.error) <= Run.__table__.c.error.type.length
        assert db.scalar(select(func.count()).select_from(ArtifactRevision)) == 0


@pytest.mark.parametrize("effect", ["cancel", "message_drift", "archive"])
def test_final_chat_binding_denies_mutation_before_dispatch(setup, effect):
    from hub.db import Conversation

    app, c, h, cfg, pid, _ = setup
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]

    def change():
        with app.state.sessions() as db:
            if effect == "cancel":
                db.scalar(select(Run)).cancel_requested = True
            elif effect == "message_drift":
                db.scalar(select(Message).where(Message.role == "user")).content = "Changed"
            else:
                db.get(Conversation, chat).archived = True
            db.commit()

    app.state.providers = FileProvider(DOCUMENT, change)
    response = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Erstelle eine Word-Datei mit einem Abschnitt."},
    )
    assert "succeeded" not in response.text
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ArtifactRevision)) == 0
        assert "artifact" not in json.loads(db.scalar(select(Run)).context_snapshot)


def test_private_chat_and_ambiguous_format_do_not_create_files(setup):
    app, c, h, cfg, pid, _ = setup
    provider = FileProvider(DOCUMENT)
    app.state.providers = provider
    for project, goal in [
        (None, "Erstelle eine Word-Datei."),
        (pid, "Erstelle Word und PDF."),
        (pid, "Erkläre eine Word-Datei."),
    ]:
        chat = c.post("/api/conversations", headers=h, json={"project_id": project}).json()["id"]
        r = c.post("/api/conversations/" + chat + "/messages", headers=h, json={"content": goal})
        assert "succeeded" not in r.text
    assert provider.calls == 0
    assert c.get("/api/projects/" + pid + "/artifacts").json() == []


@pytest.mark.parametrize(
    ("goal", "result"),
    [
        ("Erstelle eine PowerPoint-Präsentation mit 10 Folien.", ("pptx", 10)),
        ("Erstelle eine PowerPoint-Präsentation mit zehn Folien.", ("pptx", 10)),
        ("Create a PDF file with one section.", ("pdf", 3)),
        ("Erstelle eine Word-Datei.", ("docx", 3)),
    ],
)
def test_format_and_slide_count_are_bound_to_explicit_user_text(goal, result):
    assert request_format(goal) == result
