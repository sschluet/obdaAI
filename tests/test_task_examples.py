import pytest
import test_tasks
from hub.db import Task, TaskRun
from sqlalchemy import func, select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_tasks.setup.__wrapped__(tmp_path, monkeypatch)


def test_examples_are_paused_separate_local_and_do_not_reset_owner_edits(setup):
    app, c, h, cfg = setup
    assert c.post("/api/task-examples", json={}).status_code == 403
    r = c.post("/api/task-examples", headers=h, json={})
    assert r.status_code == 200, r.text
    examples = r.json()
    assert len(examples) == 2
    assert all(
        t["paused"] and t["spec"]["label"] == "LOCAL_ONLY" and t["spec"]["max_cost_usd"] == 0
        for t in examples
    )
    daily = next(t for t in examples if t["schedule"])
    assert daily["schedule"]["paused"] and daily["schedule"]["definition"]["kind"] == "daily"
    first = examples[0]
    edited = c.patch(
        "/api/tasks/" + first["id"],
        headers=h,
        json={
            "spec": first["spec"] | {"title": "My edited example"},
            "expected_revision": first["revision"],
            "expected_control_revision": first["control_revision"],
        },
    )
    assert edited.status_code == 200
    again = c.post("/api/task-examples", headers=h, json={}).json()
    assert again[0]["spec"]["title"] == "My edited example"
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 2
        assert db.scalar(select(func.count()).select_from(TaskRun)) == 0
