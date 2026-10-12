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


def test_missing_topic_asks_and_ambiguous_format_does_not_create_files(setup):
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
        if project is None:
            assert "succeeded" in r.text and "Welches Thema" in r.text
        else:
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


def file_chat(c, h, chat, goal):
    response = c.post("/api/conversations/" + chat + "/messages", headers=h, json={"content": goal})
    return response, c.get("/api/conversations/" + chat).json()["runs"][-1]


def test_chat_revision_binds_same_file_preserves_old_version_and_review_gate(setup):
    app, c, h, cfg, pid, _ = setup
    provider = FileProvider(DOCUMENT)
    app.state.providers = provider
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    _, first = file_chat(c, h, chat, "Erstelle eine Word-Datei mit einem Abschnitt.")
    artifact = first["artifact"]
    old = c.get("/api/projects/" + pid + "/artifacts").json()[0]
    provider.output = DOCUMENT.replace("Synthetische Daten.", "Kurz.")
    response, second = file_chat(c, h, chat, "Kürze die letzte Word-Datei auf einen Abschnitt.")
    assert "succeeded" in response.text, response.text
    link = second["artifact"]
    assert link["artifact_id"] == artifact["artifact_id"] and link["revision"] == 2
    assert link["base_revision"] == 1 and link["sources"] == []
    rows = c.get("/api/projects/" + pid + "/artifacts").json()
    new = next(row for row in rows if row["revision"] == 2)
    unchanged = next(row for row in rows if row["revision"] == 1)
    assert unchanged["spec"] == old["spec"] and unchanged["spec_sha256"] == old["spec_sha256"]
    assert new["draft"]["base"]["revision"] == 1
    assert new["draft"]["base"]["spec_sha256"] == old["spec_sha256"]
    assert c.get(test_artifact_api.base(pid, new) + "/download").status_code == 409
    assert "EXISTING PLAN:" in "\n".join(p.content for p in provider.parts)
    assert second["provider"] == "local" and second["cost"] is None


SLIDES = {
    "title": "Synthetische Folien",
    "slides": [
        {"title": "Bleibt", "bullets": ["Unverändert."], "notes": "Unveränderte Notiz"},
        {"title": "Kürzen", "bullets": ["Ein längerer synthetischer Satz."], "notes": ""},
    ],
}


@pytest.mark.parametrize(
    "invalid", ["none", "other_slide", "title", "missing_slide", "two_targets"]
)
def test_numbered_slide_revision_preserves_untargeted_content_and_count(setup, invalid):
    app, c, h, cfg, pid, _ = setup
    app.state.providers = FileProvider(json.dumps(SLIDES))
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    _, first = file_chat(c, h, chat, "Erstelle eine PowerPoint mit zwei Folien.")
    revised = json.loads(json.dumps(SLIDES))
    revised["slides"][1]["bullets"] = ["Kurz."]
    if invalid == "other_slide":
        revised["slides"][0]["notes"] = "Changed"
    if invalid == "title":
        revised["title"] = "Changed"
    provider = FileProvider(json.dumps(revised))
    app.state.providers = provider
    goal = {"missing_slide": "Kürze Folie 5.", "two_targets": "Kürze Folie 1 und Folie 2."}.get(
        invalid, "Kürze Folie 2."
    )
    response, run = file_chat(c, h, chat, goal)
    rows = c.get("/api/projects/" + pid + "/artifacts").json()
    if invalid == "none":
        assert "succeeded" in response.text, response.text
        assert run["artifact"]["artifact_id"] == first["artifact"]["artifact_id"]
        new = next(r for r in rows if r["revision"] == 2)
        assert len(new["spec"]["plan"]["slides"]) == 2
        assert (
            new["spec"]["plan"]["slides"][0]
            == next(r for r in rows if r["revision"] == 1)["spec"]["plan"]["slides"][0]
        )
    else:
        assert "succeeded" not in response.text and len(rows) == 1
        assert run["status"] == "failed"
        if invalid in {"missing_slide", "two_targets"}:
            assert provider.calls == 0


@pytest.mark.parametrize("drift", ["before", "during", "foreign_link", "other_conversation"])
def test_chat_revision_does_not_select_unrelated_or_stale_files(setup, drift):
    from hub.db import Artifact

    app, c, h, cfg, pid, _ = setup
    app.state.providers = FileProvider(DOCUMENT)
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    _, first = file_chat(c, h, chat, "Erstelle une Word-Datei.")
    aid = first["artifact"]["artifact_id"]

    def change():
        with app.state.sessions() as db:
            db.get(Artifact, aid).revision += 1
            db.commit()

    if drift == "before":
        change()
    if drift == "foreign_link":
        with app.state.sessions() as db:
            run = db.get(Run, first["id"])
            value = json.loads(run.context_snapshot)
            value["artifact"]["project_id"] = "ffffffff-ffff-4fff-8fff-ffffffffffff"
            run.context_snapshot = json.dumps(value)
            db.commit()
    if drift == "other_conversation":
        chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    provider = FileProvider(DOCUMENT, change if drift == "during" else None)
    app.state.providers = provider
    response, run = file_chat(c, h, chat, "Überarbeite die letzte Word-Datei.")
    assert "succeeded" not in response.text and run["status"] == "failed"
    assert len(c.get("/api/projects/" + pid + "/artifacts").json()) == 1
    assert provider.calls == (1 if drift == "during" else 0)


def test_revision_reuses_exact_sources_without_duplicate_reference_section(setup):
    app, c, h, cfg, pid, spec = setup
    source_id = spec["sources"][0]["id"]
    with app.state.sessions() as db:
        db.add(SourceChunk(source_id=source_id, locator="Page 1", content="Blue evidence."))
        db.commit()
    provider = FileProvider(DOCUMENT)
    app.state.providers = provider
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    response, first = file_chat(
        c, h, chat, "Erstelle aus den Projektunterlagen eine Word-Datei mit einem Abschnitt."
    )
    assert "succeeded" in response.text, response.text
    provider.output = DOCUMENT.replace("Synthetische Daten.", "Kurz.")
    response, second = file_chat(
        c, h, chat, "Überarbeite die letzte Word-Datei mit einem Abschnitt."
    )
    assert "succeeded" in response.text, response.text
    assert second["artifact"]["sources"] == first["artifact"]["sources"]
    existing = next(part for part in provider.parts if part.content.startswith("EXISTING PLAN:"))
    original = json.loads(existing.content.split("\n", 1)[1])
    assert len(original["sections"]) == 1
    rows = c.get("/api/projects/" + pid + "/artifacts").json()
    new = next(r for r in rows if r["revision"] == 2)
    assert len(new["spec"]["plan"]["sections"]) == 2
    assert new["spec"]["plan"]["sections"][-1]["heading"] == "Verwendete Quellen"
    assert new["draft"]["citations"][0]["source_id"] == source_id


@pytest.mark.parametrize(
    "goal",
    [
        "Überarbeite die Word-Datei Anderer Bericht.",
        "Kürze den Text.",
        "Update a Word file.",
        "Überarbeite die Word-Datei Anderer Bericht mit dem Text Letzte Woche.",
        "Überarbeite die Word-Datei Anderer Bericht mit dem Text letzte Word-Datei.",
    ],
)
def test_ambiguous_revision_does_not_guess_last_file_or_call_model(setup, goal):
    app, c, h, cfg, pid, _ = setup
    provider = FileProvider(DOCUMENT)
    app.state.providers = provider
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    _, first = file_chat(c, h, chat, "Erstelle eine Word-Datei.")
    calls = provider.calls
    response, run = file_chat(c, h, chat, goal)
    assert "succeeded" not in response.text and run["status"] == "failed"
    assert provider.calls == calls
    rows = c.get("/api/projects/" + pid + "/artifacts").json()
    assert len(rows) == 1 and rows[0]["artifact_id"] == first["artifact"]["artifact_id"]


def test_unknown_named_file_is_rejected_before_router(setup):
    app, c, h, cfg, pid, _ = setup
    provider = FileProvider(DOCUMENT)
    app.state.providers = provider
    chat = c.post("/api/conversations", headers=h, json={"project_id": pid}).json()["id"]
    _, first = file_chat(c, h, chat, "Erstelle eine Word-Datei.")

    async def unexpected_route(parts, roles):
        raise AssertionError("An ambiguous file target must not reach model classification")

    provider.route = unexpected_route
    response, run = file_chat(c, h, chat, "Überarbeite die Word-Datei Anderer Bericht.")
    assert run["status"] == "failed"
    assert run["error"].startswith("Die letzte Chat-Datei ausdrücklich benennen")
    assert provider.calls == 1
    rows = c.get("/api/projects/" + pid + "/artifacts").json()
    assert len(rows) == 1 and rows[0]["artifact_id"] == first["artifact"]["artifact_id"]
