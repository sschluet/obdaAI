"""Portable skill documents, explicit invocation and revision-bound settings."""

import pytest
from hub.db import Skill, SkillRevision
from test_chat import new_chat
from test_skills import document, enable, send, snapshot
from test_skills import setup as setup


def put(c, h, **meta):
    response = c.post(
        "/api/skills", headers=h, json={"document": document(**meta), "activate": True}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_yaml_portable_plain_import_and_permissions(setup):
    _, c, h, _ = setup
    raw = (
        "---\nname: Clear writing\ndescription: Improve clarity\nusage: mention\n---\nUse headings."
    )
    parsed = c.post("/api/skills/parse", headers=h, json={"document": raw})
    assert parsed.status_code == 200
    assert parsed.json()["invocation"] == "/clear-writing"
    s = c.post(
        "/api/skills", headers=h, json={"document": parsed.json()["document"], "activate": True}
    ).json()
    assert s["trusted"] and s["enabled"] and not s["cloud_allowed"]
    plain = c.post(
        "/api/skills/parse",
        headers=h,
        json={"document": "# My instruction\nUse plain words.", "name": "Simple"},
    )
    assert plain.status_code == 200 and plain.json()["usage"] == "mention"
    assert (
        c.post("/api/skills/parse", headers=h, json={"document": "Use plain words."}).status_code
        == 422
    )
    imported = c.post(
        "/api/skills/parse", headers=h, json={"document": document(cloud_allowed=True)}
    ).json()
    assert not imported["cloud_allowed"]  # Import never silently authorizes outbound use.


@pytest.mark.parametrize(
    "front",
    [
        "name: x\ndescription: x\ntools: [shell]",
        "name: x\ndescription: x\nallowed-tools: [shell]",
        "name: x\ndescription: &alias x\nkeywords: [*alias]",
        "name: !!python/object:module.Class {}\ndescription: x",
        "name: x\ndescription: x\n...\nname: y",
        "format: wrong\nname: x\ndescription: x",
    ],
)
def test_yaml_rejects_tools_aliases_tags_documents_and_unknown_format(setup, front):
    _, c, h, _ = setup
    assert (
        c.post(
            "/api/skills", headers=h, json={"document": "---\n" + front + "\n---\nInstruction"}
        ).status_code
        == 422
    )


def test_always_mention_keywords_and_manual_none(setup):
    app, c, h, _ = setup
    always = put(c, h, name="Always simple", usage="always", keywords=[])
    explicit = put(c, h, name="Direct mention", usage="mention", keywords=["synthetic"])
    auto = put(c, h, name="Keyword rule", usage="auto", keywords=["topic"])
    chat = new_chat(c, h)
    send(c, h, chat, "synthetic ordinary")
    assert [x["id"] for x in snapshot(app, chat)["skills"]] == [always["id"]]
    send(c, h, chat, "topic with @direct-mention.")
    used = {x["id"]: x["selection"] for x in snapshot(app, chat)["skills"]}
    assert used == {always["id"]: "always", explicit["id"]: "mention", auto["id"]: "keyword"}
    send(
        c,
        h,
        chat,
        "prefix@direct-mention /direct-mention-more example.com/direct-mention "
        "/direct-mention/path @direct-mention.com",
    )
    assert [x["id"] for x in snapshot(app, chat)["skills"]] == [always["id"]]
    url = "/api/conversations/" + chat + "/skills"
    assert (
        c.patch(url, headers=h, json={"skill_ids": [], "expected_selection": None}).status_code
        == 200
    )
    send(c, h, chat, "/direct-mention topic")
    assert snapshot(app, chat)["skills"] == []


def test_cloud_permission_revision_is_explicit_and_local_override(setup):
    app, c, h, _ = setup
    s = put(c, h, usage="always", cloud_allowed=True)
    chat = new_chat(c, h, True)
    send(c, h, chat, "No keyword needed")
    snap = snapshot(app, chat)
    assert snap["skills"][0]["label"] == "CLOUD_ALLOWED"
    assert snap["parts"][-1]["label"] == "CLOUD_ALLOWED"
    reply = c.post(
        "/api/conversations/" + chat + "/messages",
        headers=h,
        json={"content": "Now private", "local_only": True},
    )
    assert reply.status_code == 200
    assert snapshot(app, chat)["parts"][-1]["label"] == "LOCAL_ONLY"
    changed = c.patch(
        "/api/skills/" + s["id"],
        headers=h,
        json={
            "document": document(usage="always"),
            "expected_revision": s["revision"],
            "activate": True,
        },
    ).json()
    assert changed["enabled"] and changed["trusted"] and not changed["cloud_allowed"]
    assert changed["revision"] == 2
    assert enable(c, h, s).status_code == 409
    assert snap["skills"][0]["sha256"] == s["sha256"]


def test_ambiguous_invocations_and_maximum_three(setup):
    _, c, h, _ = setup
    put(c, h, name="Same name", usage="mention")
    put(c, h, name="Same-name", usage="mention")
    chat = new_chat(c, h)
    assert send(c, h, chat, "/same-name").status_code == 409
    for i in range(4):
        put(c, h, name="Always " + str(i), usage="always")
    assert send(c, h, chat, "ordinary").status_code == 409


def test_atomic_save_activate_archive_and_immutable_snapshots(setup):
    app, c, h, _ = setup
    s = put(c, h, usage="always")
    chat = new_chat(c, h)
    send(c, h, chat)
    frozen = snapshot(app, chat)
    edit = c.patch(
        "/api/skills/" + s["id"],
        headers=h,
        json={
            "document": document("New instruction", usage="mention"),
            "expected_revision": s["revision"],
            "activate": True,
        },
    )
    assert edit.status_code == 200
    current = edit.json()
    assert current["revision"] == 2 and current["enabled"] and current["trusted"]
    assert (
        c.patch(
            "/api/skills/" + s["id"],
            headers=h,
            json={"document": document(), "expected_revision": 1, "activate": True},
        ).status_code
        == 409
    )
    assert (
        c.request(
            "DELETE",
            "/api/skills/" + s["id"],
            headers=h,
            json={"expected_revision": 1, "sha256": s["sha256"]},
        ).status_code
        == 409
    )
    url = "/api/conversations/" + chat + "/skills"
    assert (
        c.patch(
            url, headers=h, json={"skill_ids": [s["id"]], "expected_selection": None}
        ).status_code
        == 200
    )
    removed = c.request(
        "DELETE",
        "/api/skills/" + s["id"],
        headers=h,
        json={"expected_revision": 2, "sha256": current["sha256"]},
    )
    assert removed.status_code == 200
    assert not c.get("/api/skills").json()
    assert send(c, h, chat).status_code == 409
    assert enable(c, h, current).status_code == 409
    assert frozen["skills"][0]["revision"] == 1
    with app.state.sessions() as db:
        assert db.get(Skill, s["id"]).archived
        assert db.get(SkillRevision, (s["id"], 1)).document == s["document"]
        assert db.get(SkillRevision, (s["id"], 2)).document == current["document"]
