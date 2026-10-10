"""Permanent deletion: FK ordering, witnesses, dependent data and managed file boundaries."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from hub import db as models
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.deletion import DeletionInput, permanently_delete, preview
from hub.deletion_cleanup import inline_cleanup
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def context(tmp_path):
    url = "sqlite:///" + str(tmp_path / "test.sqlite")
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def fk(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    models.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(models.AccountCredential(id=1, revision=0))
        db.add(models.LoginThrottle(id=1, window=0, attempts=0))
        db.commit()
    cfg = Settings(
        database_url=url,
        source_dir=str(tmp_path / "sources"),
        artifact_request_dir=str(tmp_path / "requests"),
        artifact_result_dir=str(tmp_path / "results"),
        parser_result_dir=str(tmp_path / "parsed"),
        origin="http://testserver",
        secure_cookie=False,
        password_hash=password_hash("synthetic-password"),
    )
    yield factory, cfg
    engine.dispose()


def populate(factory, cfg):
    with factory() as db:
        p = models.Project(name="Synthetisches Löschprojekt")
        other = models.Project(name="Erhalten")
        db.add_all([p, other])
        db.flush()
        c = models.Conversation(project_id=p.id, title="Testchat")
        db.add(c)
        db.flush()
        r = models.Run(conversation_id=c.id, status="succeeded")
        db.add(r)
        db.flush()
        m = models.Message(conversation_id=c.id, run_id=r.id, role="assistant", content="fixture")
        s = models.Source(project_id=p.id, name="demo.txt", sha256="a" * 64, size=7, status="ready")
        a = models.Artifact(project_id=p.id)
        skill = models.Skill(project_id=p.id)
        db.add_all([m, s, a, skill])
        db.flush()
        db.add_all(
            [
                models.RunEvent(
                    run_id=r.id, sequence=1, kind="delta", payload='{"text":"fixture"}'
                ),
                models.BudgetReservation(
                    id=r.id, provider_id="fixture", month="2026-10", ceiling=0
                ),
                models.SourceChunk(source_id=s.id, locator="1", content="fixture"),
                models.SourceReadyEvent(
                    project_id=p.id, source_id=s.id, source_revision=1, source_sha256=s.sha256
                ),
                models.ArtifactRevision(
                    artifact_id=a.id,
                    revision=1,
                    request_key=str(uuid4()),
                    spec="{}",
                    spec_sha256="a" * 64,
                    status="accepted",
                ),
                models.SkillRevision(
                    skill_id=skill.id, revision=1, document="fixture", sha256="a" * 64
                ),
                models.Research(id=r.id, project_id=p.id, query="fixture", results="[]"),
                models.ResponsePreference(key="conversation:" + c.id, revision=1),
                models.ResponsePreferenceRevision(
                    key="conversation:" + c.id, revision=1, overrides="{}", sha256="a" * 64
                ),
            ]
        )
        db.commit()
        ids = dict(
            project=p.id,
            other=other.id,
            chat=c.id,
            run=r.id,
            message=m.id,
            source=s.id,
            artifact=a.id,
            skill=skill.id,
        )
    for root, name in (
        (cfg.source_dir, s.id),
        (cfg.artifact_request_dir, a.id + "-1"),
        (cfg.artifact_result_dir, a.id + "-1"),
    ):
        path = Path(root) / name
        path.mkdir(parents=True)
        (path / "fixture").write_text("fixture")
    Path(cfg.parser_result_dir).mkdir(parents=True, exist_ok=True)
    return ids


def test_project_delete_cascades_real_fk_and_owned_files(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        p = preview(db, "project", ids["project"])
    assert not p["blockers"] and p["counts"]["conversations"] == 1
    with factory() as db:
        result = permanently_delete(
            db, cfg, "project", ids["project"], DeletionInput(expected_state=p["expected_state"])
        )
    assert result["deleted_conversation_ids"] == [ids["chat"]]
    with factory() as db:
        assert db.get(models.Project, ids["project"]) is None
        assert db.get(models.Project, ids["other"]) is not None
        for model in (
            models.SourceChunk,
            models.RunEvent,
            models.Message,
            models.Run,
            models.Source,
            models.Artifact,
            models.ArtifactRevision,
            models.Skill,
            models.SkillRevision,
            models.SourceReadyEvent,
            models.ResponsePreference,
            models.ResponsePreferenceRevision,
        ):
            assert list(db.scalars(select(model))) == []
    inline_cleanup(factory, cfg)
    assert not (Path(cfg.source_dir) / ids["source"]).exists()
    assert not (Path(cfg.artifact_result_dir) / (ids["artifact"] + "-1")).exists()


def test_chat_delete_keeps_saved_project_files_and_independent_notes(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        note = models.Memory(
            path="memories/fixture.md",
            origin="chat:" + ids["message"] + ":1",
            sha256="b" * 64,
            content="saved fixture",
        )
        db.add(note)
        db.commit()
        p = preview(db, "conversation", ids["chat"])
        assert p["counts"]["retained_memories"] == 1
    with factory() as db:
        permanently_delete(db, cfg, "conversation", ids["chat"], None)
    with factory() as db:
        assert db.get(models.Artifact, ids["artifact"])
        assert db.get(models.Source, ids["source"])
        assert db.get(models.Memory, note.id)
        assert db.get(models.Research, ids["run"]) is None
    assert (Path(cfg.source_dir) / ids["source"] / "fixture").exists()


@pytest.mark.parametrize(
    "model,key,status",
    [
        (models.Run, "run", "queued"),
        (models.Source, "source", "extracting"),
    ],
)
def test_active_work_blocks_deletion(context, model, key, status):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        row = db.get(model, ids[key])
        row.status = status
        db.commit()
    with factory() as db:
        assert preview(db, "project", ids["project"])["blockers"]
        with pytest.raises(HTTPException) as error:
            permanently_delete(db, cfg, "project", ids["project"], None)
        assert error.value.status_code == 409
    assert (Path(cfg.source_dir) / ids["source"]).exists()


def test_stale_preview_and_references_do_not_mutate(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        p = preview(db, "project", ids["project"])
        db.get(models.Project, ids["project"]).instructions = "changed"
        db.commit()
    with factory() as db:
        with pytest.raises(HTTPException) as error:
            permanently_delete(
                db,
                cfg,
                "project",
                ids["project"],
                DeletionInput(expected_state=p["expected_state"]),
            )
        assert error.value.status_code == 409
    with factory() as db:
        task = models.Task()
        db.add(task)
        db.flush()
        db.add(
            models.TaskRevision(
                task_id=task.id,
                revision=1,
                spec=json.dumps({"project_id": ids["project"]}),
                sha256="b" * 64,
            )
        )
        db.commit()
        assert any("Aufgaben" in x for x in preview(db, "project", ids["project"])["blockers"])


def test_symlink_escape_cleanup_remains_pending(context, tmp_path):
    factory, cfg = context
    ids = populate(factory, cfg)
    external = tmp_path / "external"
    external.write_text("preserved")
    (Path(cfg.source_dir) / ids["source"] / "evil").symlink_to(external)
    with factory() as db:
        result = permanently_delete(db, cfg, "project", ids["project"], None)
    inline_cleanup(factory, cfg)
    with factory() as db:
        row = db.get(models.DeletionCleanup, result["cleanup_id"])
        assert row.status == "pending" and row.error
    assert external.read_text() == "preserved"


def test_transaction_failure_preserves_records_files_and_no_cleanup_job(context, monkeypatch):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:

        def failure():
            raise RuntimeError("synthetic database failure")

        monkeypatch.setattr(db, "commit", failure)
        with pytest.raises(RuntimeError):
            permanently_delete(db, cfg, "project", ids["project"], None)
    assert (Path(cfg.source_dir) / ids["source"] / "fixture").read_text() == "fixture"
    with factory() as db:
        assert db.get(models.Project, ids["project"])


def test_api_authenticated_confirmation(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with TestClient(create_app(cfg)) as client:
        url = "/api/projects/" + ids["project"]
        assert client.get(url + "/deletion").status_code == 401
        login = client.post(
            "/api/login", json={"password": "synthetic-password"}, headers={"Origin": cfg.origin}
        )
        assert login.status_code == 200, login.text
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
        assert client.get(url).status_code == 404


def test_failed_offline_parser_can_be_deleted_with_durable_cleanup(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    inbox = Path(cfg.source_dir) / "inbox"
    inbox.mkdir()
    (inbox / (ids["source"] + ".json")).write_text("{}")
    with factory() as db:
        db.get(models.Source, ids["source"]).status = "failed"
        db.commit()
        state = preview(db, "project", ids["project"], cfg)
        assert not state["blockers"]
    with factory() as db:
        result = permanently_delete(
            db,
            cfg,
            "project",
            ids["project"],
            DeletionInput(expected_state=state["expected_state"]),
        )
        assert result["cleanup_id"]
        assert db.get(models.Project, ids["project"]) is None
    inline_cleanup(factory, cfg)
    with factory() as db:
        assert db.get(models.DeletionCleanup, result["cleanup_id"]).status == "completed"
    assert not (Path(cfg.source_dir) / ids["source"]).exists()
    assert not (inbox / (ids["source"] + ".json")).exists()


def test_budget_ledger_survives_deletion(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        reservation = db.get(models.BudgetReservation, ids["run"])
        reservation.ceiling, reservation.measured = 3, 2
        db.commit()
    with factory() as db:
        permanently_delete(db, cfg, "conversation", ids["chat"], None)
        ledger = db.get(models.BudgetReservation, ids["run"])
        assert ledger.measured == 2 and ledger.ceiling == 3


def test_saved_task_goal_copy_does_not_block_chat_delete(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        task = models.Task()
        db.add(task)
        db.flush()
        db.add(
            models.TaskRevision(
                task_id=task.id,
                revision=1,
                spec=json.dumps({"goal": "fixture", "project_id": None}),
                sha256="b" * 64,
            )
        )
        db.commit()
        assert not preview(db, "conversation", ids["chat"])["blockers"]
    with factory() as db:
        permanently_delete(db, cfg, "conversation", ids["chat"], None)
        assert db.get(models.Task, task.id)


def test_project_memory_scope_blocks_without_changing_external_memory(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        note = models.Memory(
            path="fixture.md",
            project_id=ids["project"],
            sha256="b" * 64,
            content="independent memory",
        )
        db.add(note)
        db.commit()
        assert any("Vault" in x for x in preview(db, "project", ids["project"])["blockers"])
    with factory() as db:
        with pytest.raises(HTTPException):
            permanently_delete(db, cfg, "project", ids["project"], None)
        assert db.get(models.Memory, note.id).content == "independent memory"


def test_rebound_current_task_allows_delete_preserving_old_versions(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        task = models.Task(revision=2)
        db.add(task)
        db.flush()
        old_spec = json.dumps({"project_id": ids["project"]})
        db.add_all(
            [
                models.TaskRevision(task_id=task.id, revision=1, spec=old_spec, sha256="b" * 64),
                models.TaskRevision(
                    task_id=task.id,
                    revision=2,
                    spec=json.dumps({"project_id": ids["other"]}),
                    sha256="c" * 64,
                ),
                models.TaskRun(
                    task_id=task.id,
                    task_revision=1,
                    control_revision=1,
                    request_key=str(uuid4()),
                    request_digest="a" * 64,
                    snapshot=old_spec,
                    status="succeeded",
                ),
            ]
        )
        db.commit()
        state = preview(db, "project", ids["project"], cfg)
        assert not state["blockers"]
        assert any("Sicherungen" in value for value in state["preserved"])
    with factory() as db:
        permanently_delete(
            db,
            cfg,
            "project",
            ids["project"],
            DeletionInput(expected_state=state["expected_state"]),
        )
        assert db.get(models.TaskRevision, (task.id, 1)).spec == old_spec
        assert db.get(models.Task, task.id).revision == 2
        assert (
            db.scalar(select(models.TaskRun).where(models.TaskRun.task_id == task.id)).snapshot
            == old_spec
        )


@pytest.mark.parametrize("status", ["queued", "running", "awaiting_approval"])
def test_old_revision_active_task_run_still_blocks(context, status):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        task = models.Task(revision=2)
        db.add(task)
        db.flush()
        db.add_all(
            [
                models.TaskRevision(
                    task_id=task.id,
                    revision=1,
                    spec=json.dumps({"project_id": ids["project"]}),
                    sha256="b" * 64,
                ),
                models.TaskRevision(
                    task_id=task.id, revision=2, spec='{"project_id":null}', sha256="c" * 64
                ),
                models.TaskRun(
                    task_id=task.id,
                    task_revision=1,
                    control_revision=1,
                    request_key=str(uuid4()),
                    request_digest="a" * 64,
                    snapshot=json.dumps({"project_id": ids["project"]}),
                    status=status,
                ),
            ]
        )
        db.commit()
        assert any("Aufgaben" in x for x in preview(db, "project", ids["project"])["blockers"])


def test_completed_source_event_history_detaches_with_snapshot(context):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        task = models.Task(revision=2)
        db.add(task)
        db.flush()
        old_spec = json.dumps({"project_id": ids["project"]})
        db.add_all(
            [
                models.TaskRevision(task_id=task.id, revision=1, spec=old_spec, sha256="b" * 64),
                models.TaskRevision(
                    task_id=task.id,
                    revision=2,
                    spec=json.dumps({"title": "History", "goal": "fixture", "project_id": None}),
                    sha256=hashlib.sha256(
                        json.dumps(
                            {"title": "History", "goal": "fixture", "project_id": None}
                        ).encode()
                    ).hexdigest(),
                ),
            ]
        )
        run = models.TaskRun(
            task_id=task.id,
            task_revision=1,
            control_revision=1,
            request_key=str(uuid4()),
            request_digest="a" * 64,
            snapshot=old_spec,
            status="succeeded",
        )
        db.add(run)
        db.flush()
        source_event = db.scalar(
            select(models.SourceReadyEvent).where(
                models.SourceReadyEvent.source_id == ids["source"]
            )
        )
        occurrence = models.TaskEventOccurrence(
            task_id=task.id,
            schedule_revision=1,
            event_id=source_event.id,
            status="queued",
            run_id=run.id,
        )
        db.add(occurrence)
        db.commit()
        expected = {
            column.name: getattr(source_event, column.name)
            for column in source_event.__table__.columns
        }
        state = preview(db, "project", ids["project"], cfg)
        assert not state["blockers"]
    with factory() as db:
        permanently_delete(
            db,
            cfg,
            "project",
            ids["project"],
            DeletionInput(expected_state=state["expected_state"]),
        )
        retained = db.get(models.TaskEventOccurrence, occurrence.id)
        assert retained.event_id is None
        assert json.loads(retained.deleted_event_snapshot) == expected
        assert db.get(models.TaskRun, run.id).snapshot == old_spec
        assert set(expected) == {
            "id",
            "project_id",
            "source_id",
            "source_revision",
            "source_sha256",
            "baseline",
            "created",
        }

    if cfg.database_url.startswith("sqlite"):
        with TestClient(create_app(cfg)) as client:
            login = client.post(
                "/api/login",
                json={"password": "synthetic-password"},
                headers={"Origin": cfg.origin},
            )
            assert login.status_code == 200
            response = client.get("/api/tasks/" + task.id + "/schedule/history")
            assert response.status_code == 200, response.text
            item = next(item for item in response.json() if item["id"] == occurrence.id)
            assert item["event"]["event_deleted"] is True
            assert item["event"]["source_id"] == ids["source"]
            assert item["status"] == "succeeded" and item["run_id"] == run.id


@pytest.mark.parametrize("status", ["queued", "running"])
def test_background_title_does_not_block_permanent_deletion(context, status):
    factory, cfg = context
    ids = populate(factory, cfg)
    with factory() as db:
        db.get(models.Conversation, ids["chat"]).title_status = status
        db.commit()
        assert not preview(db, "conversation", ids["chat"])["blockers"]
    with factory() as db:
        permanently_delete(db, cfg, "conversation", ids["chat"], None)
        assert db.get(models.Conversation, ids["chat"]) is None
