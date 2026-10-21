"""Paperless import and actual chat provider-boundary privacy regressions."""

import json
from uuid import uuid4

from hub.db import Message, Run, Source
from hub.integration_api import freeze_bindings
from hub.integrations import Integration, IntegrationBinding
from hub.policy import ContextPart, Privacy
from hub.routing import Route
from sqlalchemy import func, select
from test_chat import FakeProviders

pytest_plugins = ["test_knowledge", "test_chat"]


def profile(app, scope, owner):
    with app.state.sessions() as db:
        row = Integration(
            name="Synthetic archive",
            kind="paperless",
            enabled=True,
            config=json.dumps({"url": "https://archive.example.test", "auth": "api_key"}),
        )
        db.add(row)
        db.flush()
        db.add(
            IntegrationBinding(
                scope=scope,
                owner_id=owner,
                integration_ids=json.dumps([row.id]),
                selection_mode="manual",
            )
        )
        db.commit()
        return row.id


class Capturing(FakeProviders):
    def __init__(self):
        super().__init__(Route(capabilities=["chat"], model_class="cloud", reason="complex"))
        self.parts = []

    async def stream(self, parts, roles, *, external, grants):
        self.parts = parts
        async for value in super().stream(parts, roles, external=external, grants=grants):
            yield value


def test_selected_archive_reaches_local_chat_and_frozen_audit(setup, monkeypatch):
    app, client, headers, _ = setup
    chat = client.post("/api/conversations", json={"cloud_allowed": True}, headers=headers).json()
    identifier = profile(app, "conversation", chat["id"])

    async def read(factory, settings, selection, question):
        assert selection["bindings"][0]["id"] == identifier
        assert question == "Summarize Paperless document 7"
        return [
            ContextPart(
                content="PRIVATE PAPERLESS OCR",
                label=Privacy.LOCAL_ONLY,
                source_id="paperless:" + identifier + ":7",
                revision=1,
            )
        ]

    monkeypatch.setattr("hub.paperless_api.collect_context", read)
    model = Capturing()
    app.state.providers = model
    response = client.post(
        "/api/conversations/" + chat["id"] + "/messages",
        json={"content": "Summarize Paperless document 7", "request_id": str(uuid4())},
        headers=headers,
    )
    assert response.status_code == 200
    assert model.stream_calls == [False]
    assert any(p.content == "PRIVATE PAPERLESS OCR" for p in model.parts)
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == chat["id"]))
        assert run.status == "succeeded"
        assert "PRIVATE PAPERLESS OCR" in run.context_snapshot
        answer = db.scalar(
            select(Message).where(Message.run_id == run.id, Message.role == "assistant")
        )
        assert answer.label == "LOCAL_ONLY"


def test_explicit_cloud_private_archive_rejected_before_read(setup, monkeypatch):
    app, client, headers, _ = setup
    chat = client.post("/api/conversations", json={"cloud_allowed": True}, headers=headers).json()
    profile(app, "conversation", chat["id"])
    response = client.post(
        "/api/conversations/" + chat["id"] + "/messages",
        json={"content": "Read document", "model_cloud_only": True},
        headers=headers,
    )
    assert response.status_code == 409
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Run)) == 0


def test_ocr_import_preserves_original_service_and_is_idempotent(knowledge, monkeypatch):
    app, client, headers, cfg, _ = knowledge
    project = client.post(
        "/api/projects", json={"name": "Synthetic import"}, headers=headers
    ).json()
    identifier = profile(app, "project", project["id"])
    calls = []

    def read(db, settings, ident, revision, operation, document_id):
        calls.append((ident, document_id, operation.__name__))
        return {
            "id": 7,
            "title": "Synthetic receipt",
            "modified": "2026-10-11",
            "content": "Private immutable OCR",
            "content_truncated": False,
        }

    monkeypatch.setattr("hub.paperless_import_api.perform", read)
    endpoint = "/api/integrations/" + identifier + "/paperless/documents/7/import"
    body = {"expected_revision": 1, "project_id": project["id"]}
    first = client.post(endpoint, json=body, headers=headers)
    second = client.post(endpoint, json=body, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["label"] == "LOCAL_ONLY"
    assert all(operation == "document" for _, _, operation in calls)
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Source)) == 1
        source = db.get(Source, first.json()["id"])
        assert source.name.endswith("-OCR.txt")
        assert freeze_bindings(db, "project", project["id"])["bindings"][0]["kind"] == "paperless"


def test_archive_binding_change_stops_before_model(setup, monkeypatch):
    app, client, headers, _ = setup
    chat = client.post("/api/conversations", json={}, headers=headers).json()
    identifier = profile(app, "conversation", chat["id"])

    async def read(factory, settings, selection, question):
        with factory() as db:
            row = db.get(Integration, identifier)
            row.enabled = False
            db.commit()
        return [ContextPart(content="PRIVATE OCR", source_id="paperless:7", revision=1)]

    monkeypatch.setattr("hub.paperless_api.collect_context", read)
    model = Capturing()
    app.state.providers = model
    response = client.post(
        "/api/conversations/" + chat["id"] + "/messages",
        json={"content": "Paperless document 7"},
        headers=headers,
    )
    assert response.status_code == 200
    assert model.stream_calls == []
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == chat["id"]))
        assert run.status == "failed"
        assert "Integrationsauswahl" in run.error


def test_project_use_case_consumes_private_archive(knowledge, monkeypatch):
    from test_use_case_ai import Model, ai_spec

    app, client, headers, cfg, _ = knowledge
    project = client.post(
        "/api/projects", json={"name": "Synthetic linked case"}, headers=headers
    ).json()
    identifier = profile(app, "project", project["id"])
    spec = ai_spec()
    spec["processing_prompt"] = "Summarize Paperless document 7"
    case = client.post(
        "/api/use-cases", json={"spec": spec, "project_id": project["id"]}, headers=headers
    ).json()

    async def read(factory, settings, selection, question):
        assert selection["bindings"][0]["id"] == identifier
        assert question.startswith(spec["processing_prompt"])
        assert "Synthetic goal" in question
        return [ContextPart(content="PRIVATE LINKED ARCHIVE", source_id="paperless:7", revision=1)]

    monkeypatch.setattr("hub.paperless_api.collect_context", read)
    model = Model(["Synthetic archive answer"])
    app.state.providers = model
    response = client.post(
        "/api/use-cases/" + case["id"] + "/runs",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "values": {"goal": "Synthetic goal"},
        },
    )
    assert response.status_code == 200, response.text
    run = client.get("/api/use-cases/" + case["id"] + "/runs/" + response.json()["id"]).json()
    assert run["status"] == "succeeded", run
    with app.state.sessions() as db:
        execution = db.get(Run, run["execution_run_id"])
        assert "PRIVATE LINKED ARCHIVE" in execution.context_snapshot
        assert execution.provider == "local"


def test_archive_context_marks_partial_excerpts(knowledge, monkeypatch):
    import asyncio

    from hub.paperless_api import collect_context

    app, client, headers, cfg, _ = knowledge
    project = client.post(
        "/api/projects", json={"name": "Synthetic excerpt"}, headers=headers
    ).json()
    profile(app, "project", project["id"])
    with app.state.sessions() as db:
        selected = freeze_bindings(db, "project", project["id"])

    def read(db, settings, ident, revision, operation, document_id):
        return {
            "id": 7,
            "title": "Synthetic large OCR",
            "modified": "2026-10-11",
            "content": "x" * 20000,
            "content_truncated": False,
        }

    monkeypatch.setattr("hub.paperless_api.perform", read)
    parts = asyncio.run(collect_context(app.state.sessions, cfg, selected, "Dokument 7"))
    assert len(parts[0].content) <= 12000
    assert "Auszug gekürzt" in parts[0].content
    assert parts[0].label == "LOCAL_ONLY"


def test_automatic_archive_availability_does_not_read_or_block_ordinary_cloud_chat(
    setup, monkeypatch
):
    app, client, headers, provider = setup
    chat = client.post("/api/conversations", json={"cloud_allowed": True}, headers=headers).json()
    with app.state.sessions() as db:
        db.add(
            Integration(
                name="Synthetic available archive",
                kind="paperless",
                enabled=True,
                config=json.dumps({"url": "https://archive.example.test", "auth": "api_key"}),
            )
        )
        db.commit()
    monkeypatch.setattr(
        "hub.paperless_api.collect_context",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Automatic availability must not read archive")
        ),
    )
    response = client.post(
        "/api/conversations/" + chat["id"] + "/messages",
        json={"content": "Explain a public topic", "model_cloud_only": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert provider.stream_calls == [True]
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == chat["id"]))
        assert run.status == "succeeded"
        snapshot = json.loads(run.context_snapshot)
        assert snapshot["integration_selection"]["effective_mode"] == "automatic"
        assert not snapshot["sources"]
