import json
import uuid

from hub.db import Message, Run
from sqlalchemy import select
from test_chat import new_chat

pytest_plugins = ["test_chat"]


def test_edit_preserves_old_run_context_and_rebinds_privacy(setup):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers, cloud=True)
    path = f"/api/conversations/{chat_id}"
    client.post(path + "/messages", headers=headers, json={"content": "original revision"})
    detail = client.get(path).json()
    source = detail["messages"][0]
    old_run = detail["runs"][0]["id"]
    request_id = str(uuid.uuid4())
    body = {"content": "edited revision", "revision": 1, "request_id": request_id}
    r = client.patch(path + "/messages/" + source["id"], headers=headers, json=body)
    assert "event: done" in r.text
    latest = client.get(path).json()
    assert len(latest["messages"]) == 2 and len(latest["runs"]) == 2
    edited = latest["messages"][0]
    assert edited["content"] == "edited revision" and edited["revision"] == 2
    assert edited["label"] == "LOCAL_ONLY"
    old = client.get("/api/runs/" + old_run).json()
    assert old["context"]["parts"][0]["content"] == "original revision"
    assert old["context"]["parts"][0]["revision"] == 1
    assert old["answer"] == "SYNTHETIC_ANSWER"
    # Same action/key replays without another model call or another revision.
    client.patch(path + "/messages/" + source["id"], headers=headers, json=body)
    assert len(client.get(path).json()["runs"]) == 2
    body["content"] = "different action"
    assert (
        client.patch(path + "/messages/" + source["id"], headers=headers, json=body).status_code
        == 409
    )
    body["request_id"] = str(uuid.uuid4())
    assert (
        client.patch(path + "/messages/" + source["id"], headers=headers, json=body).status_code
        == 409
    )
    with app.state.sessions() as db:
        assert len(list(db.scalars(select(Message).where(Message.active.is_(False))))) == 1
        assert (
            json.loads(db.get(Run, latest["runs"][-1]["id"]).context_snapshot)["parts"][0][
                "revision"
            ]
            == 2
        )


def test_retry_is_explicit_and_idempotent_and_search_excludes_old_answers(setup):
    _, client, headers, provider = setup
    chat_id = new_chat(client, headers)
    path = "/api/conversations/" + chat_id
    client.post(path + "/messages", headers=headers, json={"content": "original_unique_fixture"})
    detail = client.get(path).json()
    client.patch(
        path + "/messages/" + detail["messages"][0]["id"],
        headers=headers,
        json={"content": "new_unique_fixture", "revision": 1},
    )
    assert client.get("/api/conversations?q=original_unique_fixture").json() == []
    request = {"request_id": str(uuid.uuid4())}
    count = provider.calls
    assert client.post(path + "/retry", headers=headers, json=request).status_code == 200
    assert provider.calls == count + 1
    assert client.post(path + "/retry", headers=headers, json=request).status_code == 200
    assert provider.calls == count + 1
    detail = client.get(path).json()
    assert len(detail["messages"]) == 2 and len(detail["runs"]) == 3
    assert client.post(path + "/retry", json=request).status_code == 403


def test_send_replay_avoids_duplicate_question(setup):
    _, client, headers, provider = setup
    path = "/api/conversations/" + new_chat(client, headers) + "/messages"
    body = {"content": "synthetic replay", "request_id": str(uuid.uuid4())}
    assert client.post(path, headers=headers, json=body).status_code == 200
    assert client.post(path, headers=headers, json=body).status_code == 200
    assert provider.calls == 1
