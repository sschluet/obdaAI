"""Read-only local search: scope, literal matching and metadata-only responses."""

import json

import pytest
from hub.db import (
    Artifact,
    ArtifactRevision,
    Conversation,
    KnowledgeConnection,
    Message,
    Project,
    Source,
    Task,
    TaskRevision,
)

pytest_plugins = ["test_chat"]


def seed(app):
    with app.state.sessions() as db:
        project = Project(name="Aurora", description="bodymarker", instructions="hiddenmarker")
        archived = Project(name="Aurora archived", archived=True)
        db.add_all([project, archived])
        db.flush()
        chat = Conversation(title="Planning", project_id=project.id)
        old = Conversation(title="Aurora archived chat", archived=True)
        db.add_all([chat, old])
        db.flush()
        db.add_all(
            [
                Message(
                    conversation_id=chat.id, role="user", content="Aurora body PRIVATE_EXCERPT"
                ),
                Message(
                    conversation_id=chat.id, role="user", content="obsoletephrase", active=False
                ),
                Source(project_id=project.id, name="Aurora.pdf", sha256="a" * 64, size=1),
                Source(
                    project_id=project.id,
                    name="Aurora old.pdf",
                    sha256="b" * 64,
                    size=1,
                    status="superseded",
                ),
                Source(project_id=archived.id, name="Aurora archived.pdf", sha256="c" * 64, size=1),
                KnowledgeConnection(
                    project_id=project.id,
                    name="Aurora library",
                    kind="smb",
                    address="https://privatehidden",
                    config='{"password":"hiddenmarker"}',
                    encrypted_secret="SECRET_MARKER",
                ),
            ]
        )
        artifact = Artifact(project_id=project.id, revision=2)
        task = Task(revision=2)
        db.add_all([artifact, task])
        db.flush()
        db.add_all(
            [
                ArtifactRevision(
                    artifact_id=artifact.id,
                    revision=1,
                    request_key="old",
                    spec=json.dumps({"plan": {"title": "obsoletephrase"}}),
                    spec_sha256="a" * 64,
                ),
                ArtifactRevision(
                    artifact_id=artifact.id,
                    revision=2,
                    request_key="current",
                    spec=json.dumps(
                        {"plan": {"title": "Aurora report", "paragraphs": ["hiddenmarker"]}}
                    ),
                    spec_sha256="b" * 64,
                ),
                TaskRevision(
                    task_id=task.id,
                    revision=1,
                    spec=json.dumps({"title": "obsoletephrase", "goal": "obsoletephrase"}),
                    sha256="a" * 64,
                ),
                TaskRevision(
                    task_id=task.id,
                    revision=2,
                    spec=json.dumps(
                        {
                            "title": "Review",
                            "goal": "Aurora goal PRIVATE_EXCERPT",
                            "project_id": project.id,
                            "steps": [{"args": "hiddenmarker"}],
                        }
                    ),
                    sha256="b" * 64,
                ),
            ]
        )
        db.commit()


def test_metadata_scope_and_relevance(setup):
    app, client, _, provider = setup
    seed(app)
    data = client.get("/api/workspace/search", params={"q": " Aurora "}).json()
    assert data["query"] == "Aurora"
    assert {r["kind"] for r in data["results"]} == {
        "project",
        "conversation",
        "source",
        "artifact",
        "task",
        "knowledge",
    }
    assert all("archived" not in r["title"] and "old" not in r["title"] for r in data["results"])
    assert [r["matched_in"] for r in data["results"]] == ["title"] * 4 + ["content"] * 2
    assert "PRIVATE_EXCERPT" not in json.dumps(data)
    assert provider.calls == 0 and provider.stream_calls == []
    for query in ("hiddenmarker", "privatehidden", "SECRET_MARKER", "obsoletephrase"):
        assert client.get("/api/workspace/search", params={"q": query}).json()["results"] == []
    assert (
        len(client.get("/api/workspace/search", params={"q": "bodymarker"}).json()["results"]) == 1
    )
    assert (
        client.get("/api/workspace/search", params={"q": "Aurora", "kind": "task"}).json()[
            "results"
        ][0]["title"]
        == "Review"
    )


@pytest.mark.parametrize("needle", ["%_", r"\x", "a%", "a_", "' OR 1=1 --"])
def test_literal_search(setup, needle):
    app, client, _, _ = setup
    with app.state.sessions() as db:
        db.add_all([Conversation(title="Prefix " + needle), Conversation(title="aXY ordinary")])
        db.commit()
    result = client.get("/api/workspace/search", params={"q": needle}).json()
    assert [r["title"] for r in result["results"]] == ["Prefix " + needle]


def test_bounded_stable_results_and_validation(setup):
    app, client, _, _ = setup
    with app.state.sessions() as db:
        db.add_all([Conversation(title=f"Aurora {i:03}") for i in range(40)])
        db.commit()
    first = client.get("/api/workspace/search", params={"q": "aurora"}).json()
    assert first == client.get("/api/workspace/search", params={"q": "aurora"}).json()
    assert len(first["results"]) == first["limit"] == 30 and first["has_more"]
    assert client.get("/api/workspace/search", params={"q": "  "}).json()["results"] == []
    for params in ({"q": "x"}, {"q": "x" * 121}, {"q": "xx", "kind": "secret"}):
        assert client.get("/api/workspace/search", params=params).status_code == 422
    client.cookies.clear()
    assert client.get("/api/workspace/search", params={"q": "Aurora"}).status_code == 401


def test_unicode_and_archived_project_tasks(setup):
    app, client, _, _ = setup
    with app.state.sessions() as db:
        project = Project(name="Hidden ÄÖ", archived=True)
        db.add(project)
        db.flush()
        db.add(Conversation(title="ÄÖ Bericht"))
        db.add(Conversation(title="ÄÖ hidden chat", project_id=project.id))
        for archived, linked in [(True, False), (False, True)]:
            task = Task(archived=archived)
            db.add(task)
            db.flush()
            db.add(
                TaskRevision(
                    task_id=task.id,
                    revision=1,
                    sha256="a" * 64,
                    spec=json.dumps(
                        {
                            "title": "ÄÖ hidden",
                            "goal": "ÄÖ hidden",
                            "project_id": project.id if linked else None,
                        }
                    ),
                )
            )
        db.commit()
    assert [
        r["title"]
        for r in client.get("/api/workspace/search", params={"q": "äö"}).json()["results"]
    ] == ["ÄÖ Bericht"]


def test_paused_knowledge_metadata_remains_discoverable(setup):
    app, client, _, _ = setup
    with app.state.sessions() as db:
        project = Project(name="Dormant", kind="knowledge", archived=True)
        db.add(project)
        db.flush()
        db.add(
            KnowledgeConnection(
                project_id=project.id,
                name="Paused Library",
                kind="smb",
                status="needs_setup",
                enabled=False,
                address="addressmarker",
                config='{"username":"configmarker"}',
            )
        )
        db.add(Source(project_id=project.id, name="Paused Library source", sha256="a" * 64, size=1))
        db.commit()
    results = client.get("/api/workspace/search", params={"q": "Paused Library"}).json()["results"]
    assert len(results) == 1 and results[0]["kind"] == "knowledge"
    for query in ("addressmarker", "configmarker"):
        assert client.get("/api/workspace/search", params={"q": query}).json()["results"] == []


def test_standalone_chat_files_are_searchable_in_their_exact_active_chat(setup):
    app, client, _, _ = setup
    with app.state.sessions() as db:
        active = Conversation(title="Active file chat")
        archived = Conversation(title="Archived file chat", archived=True)
        db.add_all([active, archived])
        db.flush()
        active_id = active.id
        for chat in [active, archived]:
            file = Artifact(conversation_id=chat.id)
            db.add(file)
            db.flush()
            db.add(
                ArtifactRevision(
                    artifact_id=file.id,
                    revision=1,
                    request_key=file.id,
                    spec=json.dumps(
                        {
                            "sources": [],
                            "plan": {
                                "kind": "docx",
                                "title": "ChatReport",
                                "sections": [
                                    {"heading": "Private", "paragraphs": ["PRIVATE_BODY"]}
                                ],
                            },
                        }
                    ),
                    spec_sha256="a" * 64,
                )
            )
        db.commit()
    result = client.get(
        "/api/workspace/search", params={"q": "ChatReport", "kind": "artifact"}
    ).json()
    assert len(result["results"]) == 1
    assert result["results"][0]["project_id"] is None
    assert result["results"][0]["conversation_id"] == active_id
    assert "PRIVATE_BODY" not in json.dumps(result)
