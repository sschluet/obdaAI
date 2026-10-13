import json

import pytest
import test_chat
from hub.db import ActionGrant, Run, SkillRevision
from sqlalchemy import func, select
from test_chat import new_chat


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def document(body="Antworte als Tabelle.", **extra):
    return (
        "---\n"
        + json.dumps(
            {
                "format": "obdaai-skill-1",
                "name": "Synthetic format",
                "keywords": ["synthetic"],
                **extra,
            }
        )
        + "\n---\n"
        + body
    )


def create(c, h, **extra):
    r = c.post("/api/skills", headers=h, json={"document": document(), **extra})
    assert r.status_code == 200, r.text
    return r.json()


def enable(c, h, s, enabled=True):
    return c.post(
        "/api/skills/" + s["id"] + "/trust",
        headers=h,
        json={"expected_revision": s["revision"], "sha256": s["sha256"], "enabled": enabled},
    )


def snapshot(app, chat):
    with app.state.sessions() as db:
        row = db.scalar(select(Run).where(Run.conversation_id == chat).order_by(Run.started.desc()))
        return json.loads(row.context_snapshot)


def send(c, h, chat, content="synthetic question"):
    return c.post("/api/conversations/" + chat + "/messages", headers=h, json={"content": content})


def test_import_untrusted_exact_hash_edit_immutable_and_run_snapshot(setup):
    app, c, h, _ = setup
    s = create(c, h)
    assert not s["enabled"] and not s["trusted"]
    chat = new_chat(c, h)
    assert send(c, h, chat).status_code == 200
    assert snapshot(app, chat)["skills"] == []
    assert (
        c.post(
            "/api/skills/" + s["id"] + "/trust",
            headers=h,
            json={"expected_revision": 1, "sha256": "0" * 64, "enabled": True},
        ).status_code
        == 409
    )
    assert enable(c, h, s).status_code == 200
    send(c, h, chat)
    first = snapshot(app, chat)
    assert first["skills"][0]["sha256"] == s["sha256"]
    assert first["parts"][-1]["label"] == "LOCAL_ONLY"
    assert "Tabelle" in first["parts"][-1]["content"]
    revised = c.patch(
        "/api/skills/" + s["id"],
        headers=h,
        json={"document": document("Antworte in einem Satz."), "expected_revision": 1},
    ).json()
    assert revised["revision"] == 2 and not revised["enabled"] and not revised["trusted"]
    assert enable(c, h, s).status_code == 409
    assert enable(c, h, revised).status_code == 200
    send(c, h, chat)
    second = snapshot(app, chat)
    assert "einem Satz" in second["parts"][-1]["content"]
    assert second["skills"][0]["revision"] == 2
    assert second["skills"][0]["sha256"] != first["skills"][0]["sha256"]
    history = c.get("/api/skills/" + s["id"] + "/revisions").json()
    assert [r["revision"] for r in history] == [1, 2] and history[0]["document"] == s["document"]
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ActionGrant)) == 0
        assert db.get(SkillRevision, (s["id"], 1)).document == s["document"]


def test_project_isolation_manual_override_and_revocation(setup):
    app, c, h, _ = setup
    p = c.post("/api/projects", headers=h, json={"name": "Synthetic scope"}).json()
    s = create(c, h, project_id=p["id"])
    enable(c, h, s)
    global_chat = new_chat(c, h)
    send(c, h, global_chat)
    assert snapshot(app, global_chat)["skills"] == []
    url = "/api/conversations/" + global_chat + "/skills"
    assert c.patch(url, headers=h, json={"skill_ids": [s["id"]]}).status_code == 409
    chat = c.post("/api/conversations", headers=h, json={"project_id": p["id"]}).json()["id"]
    url = "/api/conversations/" + chat + "/skills"
    assert (
        c.patch(url, headers=h, json={"skill_ids": [], "expected_selection": None}).status_code
        == 200
    )
    send(c, h, chat)
    assert snapshot(app, chat)["skills"] == []
    assert (
        c.patch(
            url, headers=h, json={"skill_ids": [s["id"]], "expected_selection": None}
        ).status_code
        == 409
    )
    assert (
        c.patch(url, headers=h, json={"skill_ids": [s["id"]], "expected_selection": []}).status_code
        == 200
    )
    send(c, h, chat, "no keyword match")
    assert snapshot(app, chat)["skills"][0]["selection"] == "manual"
    enable(c, h, s, False)
    assert send(c, h, chat).status_code == 409


@pytest.mark.parametrize(
    "bad",
    [
        "---\nname: unsafe\n---\ntext",
        document(tools=["shell"]),
        document(enabled=True),
        document(label="CLOUD_ALLOWED"),
        document(keywords=[""]),
        document(""),
    ],
)
def test_skill_format_cannot_import_permissions(setup, bad):
    _, c, h, _ = setup
    assert c.post("/api/skills", headers=h, json={"document": bad}).status_code == 422


def test_no_auto_match_and_cloud_privacy_of_skills(setup):
    app, c, h, provider = setup
    s = create(c, h)
    enable(c, h, s)
    chat = new_chat(c, h, True)
    send(c, h, chat, "without matching keyword")
    assert snapshot(app, chat)["skills"] == []
    send(c, h, chat)
    assert snapshot(app, chat)["parts"][-1]["label"] == "LOCAL_ONLY"
    assert provider.stream_calls == [True, False]
