"""0041 preserves project artifacts and prevents loss of conversation outputs."""

import json
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from hub.artifact_runner import canonical
from hub.artifact_specs import ArtifactSpec
from hub.artifacts import digest
from hub.config import Settings
from hub.db import (
    Artifact,
    ArtifactRevision,
    Conversation,
    DeletionCleanup,
    Project,
    session_factory,
)
from hub.deletion import DeletionInput, permanently_delete, preview
from hub.deletion_cleanup import inline_cleanup
from sqlalchemy import create_engine, delete, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import with_loader_criteria


def test_chat_artifact_migration_preserves_existing_and_blocks_destructive_downgrade(
    tmp_path, monkeypatch
):
    url = "sqlite:///" + str(tmp_path / "migration.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "0040")
    engine = create_engine(url)
    pid, aid, cid = (str(uuid.uuid4()) for _ in range(3))
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO projects(id,name,description,instructions,label,archived,revision) "
                "VALUES(:id,'Original','','','LOCAL_ONLY',0,1)"
            ),
            {"id": pid},
        )
        db.execute(
            text("INSERT INTO artifacts(id,project_id,revision,created) VALUES(:id,:pid,3,1)"),
            {"id": aid, "pid": pid},
        )
    command.upgrade(config, "0041")
    with engine.connect() as db:
        row = db.execute(
            text("SELECT project_id,conversation_id,revision FROM artifacts WHERE id=:id"),
            {"id": aid},
        ).one()
        assert tuple(row) == (pid, None, 3)
    factory = session_factory(url)
    with factory() as db:
        db.add(Conversation(id=cid))
        db.flush()
        chat_artifact = Artifact(conversation_id=cid)
        db.add(chat_artifact)
        db.commit()
        chat_aid = chat_artifact.id
    with pytest.raises(RuntimeError, match="Preserve conversation artifacts"):
        command.downgrade(config, "0040")
    with factory() as db:
        assert db.get(Artifact, chat_aid)
        db.execute(delete(Artifact).where(Artifact.id == chat_aid))
        db.execute(delete(Conversation).where(Conversation.id == cid))
        db.commit()
    command.downgrade(config, "0040")
    assert "conversation_id" not in {
        col["name"] for col in inspect(engine).get_columns("artifacts")
    }
    command.upgrade(config, "0041")
    with factory() as db:
        assert db.get(Artifact, aid).project_id == pid
    engine.dispose()


def finish_owned_cleanup(factory, cfg, cleanup_id, artifact_id):
    """Run real filesystem reconciliation while selecting only this fixture's job."""

    def owned_factory():
        db = factory()

        @event.listens_for(db, "do_orm_execute")
        def scoped_cleanup(statement):
            if statement.is_select:
                statement.statement = statement.statement.options(
                    with_loader_criteria(DeletionCleanup, DeletionCleanup.id == cleanup_id)
                )

        return db

    with factory() as db:
        cleanup = db.get(DeletionCleanup, cleanup_id)
        assert cleanup is not None
        items = json.loads(cleanup.manifest)
        assert items and all(
            item["kind"] == "artifact" and item["id"] == artifact_id for item in items
        )
    inline_cleanup(owned_factory, cfg)
    with factory() as db:
        cleanup = db.get(DeletionCleanup, cleanup_id)
        assert cleanup is not None and cleanup.status == "completed", (
            cleanup.error if cleanup else "Missing cleanup job"
        )
    for folder in (cfg.artifact_request_dir, cfg.artifact_result_dir):
        assert not (Path(folder) / (artifact_id + "-1")).exists()
        assert not list(Path(folder).glob("." + artifact_id + "-1-*"))


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG fixture required")
def test_chat_artifact_postgres_fk_deletion_and_owner_constraint(tmp_path, monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only loopback hub_ci is allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    factory = session_factory(url)
    cfg = Settings(
        database_url=url,
        artifact_request_dir=str(tmp_path / "requests"),
        artifact_result_dir=str(tmp_path / "results"),
    )
    for folder in (cfg.artifact_request_dir, cfg.artifact_result_dir):
        Path(folder).mkdir()
    cleanup_id = None
    with factory() as db:
        owned, sibling = Conversation(), Conversation()
        project = Project(name="Synthetic scoped artifact")
        db.add_all([owned, sibling, project])
        db.flush()
        cid, sibling_cid, pid = owned.id, sibling.id, project.id
        artifact = Artifact(conversation_id=cid)
        kept = Artifact(project_id=pid)
        db.add_all([artifact, kept])
        db.flush()
        aid, kept_aid = artifact.id, kept.id
        spec = ArtifactSpec.model_validate(
            {
                "plan": {
                    "kind": "docx",
                    "title": "Synthetic private result",
                    "sections": [{"heading": "Content"}],
                }
            }
        )
        document = canonical(spec)
        db.add(
            ArtifactRevision(
                artifact_id=aid,
                revision=1,
                request_key=str(uuid.uuid4()),
                spec=document,
                spec_sha256=digest(document),
                status="cancelled",
            )
        )
        db.commit()
    try:
        with factory() as db:
            db.add(Artifact(project_id=pid, conversation_id=sibling_cid))
            with pytest.raises(IntegrityError):
                db.commit()
        with factory() as db:
            state = preview(db, "conversation", cid, cfg)
            assert state["counts"]["artifacts"] == 1
            deleted = permanently_delete(
                db, cfg, "conversation", cid, DeletionInput(expected_state=state["expected_state"])
            )
            cleanup_id = deleted["cleanup_id"]
        assert cleanup_id
        finish_owned_cleanup(factory, cfg, cleanup_id, aid)
        with factory() as db:
            assert db.get(Conversation, cid) is None
            assert db.get(Artifact, aid) is None
            assert db.get(ArtifactRevision, (aid, 1)) is None
            assert db.get(Artifact, kept_aid) and db.get(Conversation, sibling_cid)
    finally:
        with factory() as db:
            if cleanup_id:
                db.execute(delete(DeletionCleanup).where(DeletionCleanup.id == cleanup_id))
            db.execute(delete(ArtifactRevision).where(ArtifactRevision.artifact_id == aid))
            db.execute(delete(Artifact).where(Artifact.id.in_([aid, kept_aid])))
            db.execute(delete(Conversation).where(Conversation.id.in_([cid, sibling_cid])))
            db.execute(delete(Project).where(Project.id == pid))
            db.commit()


def test_owned_fixture_cleanup_preserves_other_pending_queue(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "cleanup.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    factory = session_factory(url)
    cfg = Settings(
        database_url=url,
        artifact_request_dir=str(tmp_path / "requests"),
        artifact_result_dir=str(tmp_path / "results"),
    )
    for folder in (cfg.artifact_request_dir, cfg.artifact_result_dir):
        Path(folder).mkdir()
    own_id, other_id, aid = (str(uuid.uuid4()) for _ in range(3))
    with factory() as db:
        db.add(
            DeletionCleanup(
                id=own_id,
                manifest=json.dumps(
                    [{"cleanup_id": own_id, "kind": "artifact", "id": aid, "revision": 1}]
                ),
                source_done=True,
                artifact_done=False,
            )
        )
        db.add(DeletionCleanup(id=other_id, manifest="[]", source_done=False, artifact_done=False))
        db.commit()
    finish_owned_cleanup(factory, cfg, own_id, aid)
    with factory() as db:
        other = db.get(DeletionCleanup, other_id)
        assert other.status == "pending" and not other.source_done and not other.artifact_done
        assert other.error == "" and other.finished is None
