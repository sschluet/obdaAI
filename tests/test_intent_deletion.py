"""Permanent parent deletion includes exactly owned private intent workspaces."""

import json

import pytest
import test_deletion
from fastapi import HTTPException
from hub import db as models
from hub.deletion import DeletionInput, permanently_delete, preview
from sqlalchemy import select


@pytest.fixture
def context(tmp_path):
    yield from test_deletion.context.__wrapped__(tmp_path)


def add_intent(db, owner, *, status="succeeded", snapshot=None, purpose="intent"):
    hidden = models.Conversation(title="Synthetic interpretation", purpose=purpose)
    db.add(hidden)
    db.flush()
    run = models.Run(
        conversation_id=hidden.id, status=status,
        context_snapshot=json.dumps({"request_owner": owner, "goal": "Synthetic private goal"})
        if snapshot is None else snapshot,
    )
    db.add(run)
    db.flush()
    db.add_all([
        models.RunEvent(run_id=run.id, sequence=1, kind="delta", payload='{"text":"synthetic"}'),
        models.Message(conversation_id=hidden.id, run_id=run.id, role="user", content="Synthetic"),
    ])
    return hidden.id, run.id


@pytest.mark.parametrize("kind", ["conversation", "project"])
def test_preview_and_actual_delete_include_failed_and_succeeded_owned_intents_only(context, kind):
    factory, cfg = context
    with factory() as db:
        project = models.Project(name="Synthetic project")
        db.add(project)
        db.flush()
        parent = models.Conversation(title="Synthetic chat", project_id=project.id)
        other = models.Conversation(title="Unrelated synthetic chat")
        db.add_all([parent, other])
        db.flush()
        ids = [add_intent(db, parent.id, status=status) for status in ["failed", "succeeded"]]
        unrelated = add_intent(db, other.id)
        malformed = [add_intent(db, parent.id, snapshot=snapshot) for snapshot in [
            '{"request_owner":', json.dumps({"request_owner": parent.id + "-suffix"}),
            json.dumps({"nested": {"request_owner": parent.id}}),
            json.dumps({"request_owner": [parent.id]}),
            json.dumps([{"request_owner": parent.id}]),
        ]]
        ordinary = add_intent(db, parent.id, purpose="chat")
        db.commit()
        parent_id, project_id = parent.id, project.id
    target = parent_id if kind == "conversation" else project_id
    with factory() as db:
        state = preview(db, kind, target)
        assert state["counts"]["conversations"] == 3
        assert state["counts"]["runs"] == 2
        assert not state["blockers"]
    with factory() as db:
        result = permanently_delete(db, cfg, kind, target,
                                    DeletionInput(expected_state=state["expected_state"]))
        assert set(result["deleted_conversation_ids"]) == {parent_id, *(h for h, _ in ids)}
    with factory() as db:
        for hidden, run_id in ids:
            assert db.get(models.Conversation, hidden) is None
            assert db.get(models.Run, run_id) is None
            assert not list(db.scalars(select(models.RunEvent).where(
                models.RunEvent.run_id == run_id)))
            assert not list(db.scalars(select(models.Message).where(
                models.Message.conversation_id == hidden)))
        for hidden, run_id in [unrelated, *malformed, ordinary]:
            assert db.get(models.Conversation, hidden) is not None
            assert db.get(models.Run, run_id) is not None
        assert db.get(models.Conversation, other.id) is not None


@pytest.mark.parametrize("status", ["queued", "routing", "streaming"])
def test_active_owned_intent_blocks_parent_deletion(context, status):
    factory, cfg = context
    with factory() as db:
        parent = models.Conversation(title="Synthetic active parent")
        db.add(parent)
        db.flush()
        hidden, run_id = add_intent(db, parent.id, status=status)
        db.commit()
        parent_id = parent.id
    with factory() as db:
        state = preview(db, "conversation", parent_id)
        assert state["counts"]["runs"] == 1 and state["blockers"]
    with factory() as db:
        with pytest.raises(HTTPException) as error:
            permanently_delete(db, cfg, "conversation", parent_id,
                               DeletionInput(expected_state=state["expected_state"]))
        assert error.value.status_code == 409
        db.rollback()
        assert db.get(models.Conversation, parent_id) is not None
        assert db.get(models.Conversation, hidden) is not None
        assert db.get(models.Run, run_id).status == status


def test_new_or_changed_owned_intent_invalidates_confirmation_witness(context):
    factory, cfg = context
    with factory() as db:
        parent = models.Conversation(title="Synthetic parent")
        db.add(parent)
        db.commit()
        parent_id = parent.id
    with factory() as db:
        old = preview(db, "conversation", parent_id)
    with factory() as db:
        _, run_id = add_intent(db, parent_id)
        db.commit()
    with factory() as db:
        fresh = preview(db, "conversation", parent_id)
        assert fresh["expected_state"] != old["expected_state"]
        with pytest.raises(HTTPException) as error:
            permanently_delete(db, cfg, "conversation", parent_id,
                               DeletionInput(expected_state=old["expected_state"]))
        assert error.value.status_code == 409
        db.rollback()
        db.get(models.Run, run_id).error = "Synthetic changed state"
        db.commit()
    with factory() as db:
        assert preview(db, "conversation", parent_id)["expected_state"] != fresh["expected_state"]
