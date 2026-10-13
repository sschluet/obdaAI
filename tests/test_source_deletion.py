"""Single-source deletion with real FKs, durable storage and retained answer snapshots."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from hub import db as models
from hub.api import create_app
from hub.deletion import DeletionInput
from hub.deletion_cleanup import inline_cleanup
from hub.knowledge import extract_source, retrieve
from hub.source_deletion import permanently_delete, preview
from sqlalchemy import select
from test_deletion import populate

pytest_plugins = ["test_deletion", "test_deletion_postgres"]


def remove(factory, cfg, ids, state=None):
    with factory() as db:
        state = state or preview(db, ids["project"], ids["source"])
    with factory() as db:
        return permanently_delete(
            db,
            cfg,
            ids["project"],
            ids["source"],
            DeletionInput(expected_state=state["expected_state"]),
        )


@pytest.mark.parametrize("fixture_name", ["context", "pg_context"])
def test_one_source_preserves_other_sources_and_saved_context(request, fixture_name):
    factory, cfg = request.getfixturevalue(fixture_name)
    ids = populate(factory, cfg)
    with factory() as db:
        sibling = models.Source(
            project_id=ids["project"], name="keep.txt", size=1, sha256="b" * 64, status="ready"
        )
        db.add(sibling)
        db.flush()
        db.add(models.SourceChunk(source_id=sibling.id, content="fixture", locator="1"))
        answer = db.get(models.Message, ids["message"])
        answer.content = "Answer with citation " + ids["source"]
        artifact = db.get(models.ArtifactRevision, (ids["artifact"], 1))
        artifact.spec = json.dumps({"sources": [{"id": ids["source"]}]})
        db.commit()
        state = preview(db, ids["project"], ids["source"])
        assert state["counts"]["chunks"] == 1 and not state["blockers"]
    result = remove(factory, cfg, ids, state)
    assert result["deleted_source_id"] == ids["source"]
    assert (Path(cfg.source_dir) / ids["source"]).exists()  # bytes removed only by durable owner
    with factory() as db:
        assert db.get(models.Source, ids["source"]) is None
        assert db.get(models.Source, sibling.id) is not None
        assert db.get(models.Project, ids["project"]) is not None
        assert db.get(models.Conversation, ids["chat"]) is not None
        assert db.get(models.Message, ids["message"]).content == answer.content
        assert db.get(models.ArtifactRevision, (ids["artifact"], 1)).spec == artifact.spec
        assert [r["source_id"] for r in retrieve(db, ids["project"], "fixture")] == [sibling.id]
        assert db.get(models.DeletionCleanup, result["cleanup_id"]).status == "pending"
    inline_cleanup(factory, cfg)
    assert not (Path(cfg.source_dir) / ids["source"]).exists()
    assert (Path(cfg.artifact_result_dir) / (ids["artifact"] + "-1")).exists()


@pytest.mark.parametrize("status", ["queued", "extracting"])
def test_active_extraction_is_blocked(context, status):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        db.get(models.Source, ids["source"]).status = status
        db.commit()
    with pytest.raises(HTTPException) as error:
        remove(factory, cfg, ids)
    assert error.value.status_code == 409
    assert (Path(cfg.source_dir) / ids["source"]).exists()


def test_stale_preview_and_wrong_project_cannot_delete(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        state = preview(db, ids["project"], ids["source"])
        db.get(models.Source, ids["source"]).revision += 1
        db.commit()
        with pytest.raises(HTTPException) as error:
            preview(db, ids["other"], ids["source"])
        assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        remove(factory, cfg, ids, state)
    assert error.value.status_code == 409


@pytest.mark.parametrize("dependency", ["chat", "artifact", "task", "action"])
def test_live_dependencies_block_without_mutating_context(context, dependency):
    factory, cfg = context
    ids = populate(factory, cfg)
    spec = json.dumps({"sources": [{"id": ids["source"]}]})
    with factory() as db:
        if dependency == "chat":
            db.get(models.Run, ids["run"]).status = "streaming"
        elif dependency == "artifact":
            row = db.get(models.ArtifactRevision, (ids["artifact"], 1))
            row.status, row.spec = "rendering", spec
        elif dependency == "task":
            task = models.Task()
            db.add(task)
            db.flush()
            db.add(models.TaskRevision(task_id=task.id, revision=1, spec=spec, sha256="a" * 64))
        else:
            db.add(
                models.ActionIntent(
                    request_key=str(uuid4()),
                    tool_id="fixture",
                    tool_revision=1,
                    parameters=spec,
                    parameters_sha256="a" * 64,
                    policy_revision=1,
                    status="proposed",
                )
            )
        db.commit()
    with pytest.raises(HTTPException) as error:
        remove(factory, cfg, ids)
    assert error.value.status_code == 409
    with factory() as db:
        assert db.get(models.Source, ids["source"])


def test_knowledge_copy_detach_preserves_external_connection(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        connection = models.KnowledgeConnection(
            project_id=ids["project"], name="Synthetic", kind="obsidian", status="ready"
        )
        db.add(connection)
        db.flush()
        doc = models.KnowledgeDocument(
            connection_id=connection.id,
            path="external.txt",
            fingerprint="a" * 64,
            source_id=ids["source"],
        )
        db.add(doc)
        db.commit()
        state = preview(db, ids["project"], ids["source"])
        assert state["counts"]["linked_knowledge_documents"] == 1
        assert any("wieder importieren" in p for p in state["preserved"])
        connection.status = "indexing"
        db.commit()
    with pytest.raises(HTTPException):
        remove(factory, cfg, ids)
    with factory() as db:
        db.get(models.KnowledgeConnection, connection.id).status = "ready"
        db.commit()
    remove(factory, cfg, ids)
    with factory() as db:
        assert db.get(models.KnowledgeConnection, connection.id)
        assert db.get(models.KnowledgeDocument, doc.id) is None


@pytest.mark.parametrize("fixture_name", ["context", "pg_context"])
def test_source_event_snapshot_preserved(request, fixture_name):
    factory, cfg = request.getfixturevalue(fixture_name)
    ids = populate(factory, cfg)
    with factory() as db:
        task = models.Task()
        db.add(task)
        db.flush()
        event = db.scalar(
            select(models.SourceReadyEvent).where(
                models.SourceReadyEvent.source_id == ids["source"]
            )
        )
        occurrence = models.TaskEventOccurrence(
            task_id=task.id, schedule_revision=1, event_id=event.id, status="skipped"
        )
        db.add(occurrence)
        db.commit()
        snapshot = {c.name: getattr(event, c.name) for c in event.__table__.columns}
    remove(factory, cfg, ids)
    with factory() as db:
        row = db.get(models.TaskEventOccurrence, occurrence.id)
        assert row.event_id is None
        assert json.loads(row.deleted_event_snapshot) == snapshot


def test_authenticated_api_requires_confirmation_and_csrf(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    url = f"/api/projects/{ids['project']}/sources/{ids['source']}"
    with TestClient(create_app(cfg)) as client:
        assert client.get(url + "/deletion").status_code == 401
        login = client.post(
            "/api/login", json={"password": "synthetic-password"}, headers={"Origin": cfg.origin}
        )
        headers = {"Origin": cfg.origin, "X-CSRF-Token": login.json()["csrf"]}
        state = client.get(url + "/deletion").json()
        assert client.delete(url, headers=headers).status_code == 422
        assert (
            client.request(
                "DELETE",
                url,
                json={"expected_state": state["expected_state"]},
                headers={"Origin": cfg.origin},
            ).status_code
            == 403
        )
        response = client.request(
            "DELETE", url, json={"expected_state": state["expected_state"]}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert client.get(url + "/deletion").status_code == 404
        assert client.get(f"/api/projects/{ids['project']}").status_code == 200


def test_deleted_source_cannot_be_recreated_by_old_extraction(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    remove(factory, cfg, ids)
    asyncio.run(extract_source(factory, cfg, ids["source"]))
    inline_cleanup(factory, cfg)
    assert not (Path(cfg.source_dir) / ids["source"]).exists()


def test_cleanup_all_source_revision_results_only(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        db.get(models.Source, ids["source"]).revision = 3
        db.commit()
    for revision in range(1, 4):
        (Path(cfg.parser_result_dir) / f"{ids['source']}-{revision}.json").write_text("{}")
    other = Path(cfg.parser_result_dir) / (str(uuid4()) + "-1.json")
    other.write_text("{}")
    remove(factory, cfg, ids)
    inline_cleanup(factory, cfg)
    assert all(
        not (Path(cfg.parser_result_dir) / f"{ids['source']}-{r}.json").exists()
        for r in range(1, 4)
    )
    assert hashlib.sha256(other.read_bytes()).hexdigest() == hashlib.sha256(b"{}").hexdigest()


def test_running_task_with_implicit_project_context_blocks(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        task = models.Task()
        db.add(task)
        db.flush()
        db.add(
            models.TaskRun(
                task_id=task.id,
                task_revision=1,
                control_revision=1,
                request_key=str(uuid4()),
                request_digest="a" * 64,
                snapshot=json.dumps({"project_id": ids["project"]}),
                status="running",
            )
        )
        db.commit()
    with pytest.raises(HTTPException) as error:
        remove(factory, cfg, ids)
    assert error.value.status_code == 409


@pytest.mark.parametrize("project_relation", [None, "other"])
def test_detached_active_answer_with_source_snapshot_blocks(context, project_relation):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        chat = models.Conversation(project_id=ids["other"] if project_relation else None)
        db.add(chat)
        db.flush()
        run = models.Run(
            conversation_id=chat.id,
            status="streaming",
            context_snapshot=json.dumps({"sources": [{"source_id": ids["source"]}]}),
        )
        db.add(run)
        db.commit()
    with pytest.raises(HTTPException) as error:
        remove(factory, cfg, ids)
    assert error.value.status_code == 409
    with factory() as db:
        db.get(models.Run, run.id).status = "succeeded"
        db.commit()
    remove(factory, cfg, ids)
    with factory() as db:
        assert db.get(models.Run, run.id).context_snapshot == run.context_snapshot


def test_unrelated_active_answer_does_not_block_source_deletion(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        chat = models.Conversation()
        db.add(chat)
        db.flush()
        run = models.Run(
            conversation_id=chat.id,
            status="streaming",
            context_snapshot=json.dumps({"sources": [{"source_id": str(uuid4())}]}),
        )
        db.add(run)
        db.commit()
    remove(factory, cfg, ids)
    with factory() as db:
        assert db.get(models.Run, run.id).status == "streaming"
