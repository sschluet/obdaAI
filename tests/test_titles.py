"""Synthetic derivatives: manual edits, deletion and local failure remain safe."""

import asyncio

import pytest
from hub.db import Conversation, Message
from hub.policy import Privacy
from hub.titles import ensure_initial_title, execute_title, initial_title, reserve_title
from test_chat import new_chat

pytest_plugins = ["test_chat"]


def pending(app, chat_id):
    with app.state.sessions() as db:
        db.add(Message(conversation_id=chat_id, role="user", content="synthetic input"))
        db.flush()
        reserve_title(db, app.state.settings, chat_id)
        db.commit()


def test_title_idempotency_and_manual_title_before_generation(setup):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    pending(app, chat_id)

    class Provider:
        calls = 0

        async def title(self, parts, roles):
            self.calls += 1
            assert parts[0].label == Privacy.LOCAL_ONLY
            return "Synthetic generated title"

    provider = Provider()
    asyncio.run(execute_title(app.state.sessions, provider, chat_id))
    asyncio.run(execute_title(app.state.sessions, provider, chat_id))
    assert provider.calls == 1
    assert client.get("/api/conversations/" + chat_id).json()["title_status"] == "generated"
    other = new_chat(client, headers)
    pending(app, other)
    client.patch("/api/conversations/" + other, json={"title": "Neues Gespräch"}, headers=headers)
    asyncio.run(execute_title(app.state.sessions, provider, other))
    assert provider.calls == 1
    detail = client.get("/api/conversations/" + other).json()
    assert detail["title"] == "Neues Gespräch" and detail["title_status"] == "manual"


@pytest.mark.parametrize("action", ["rename", "delete", "fail", "interrupt"])
def test_changes_during_generation_and_failure(setup, action):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    pending(app, chat_id)

    class Provider:
        async def title(self, parts, roles):
            if action == "rename":
                assert (
                    client.patch(
                        "/api/conversations/" + chat_id,
                        json={"title": "My manual title"},
                        headers=headers,
                    ).status_code
                    == 200
                )
            if action == "delete":
                assert (
                    client.delete("/api/conversations/" + chat_id, headers=headers).status_code
                    == 200
                )
            if action == "fail":
                raise ValueError("PRIVATE_PROVIDER_FAILURE")
            if action == "interrupt":
                raise asyncio.CancelledError
            return "Generated title"

    if action == "interrupt":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(execute_title(app.state.sessions, Provider(), chat_id))
    else:
        asyncio.run(execute_title(app.state.sessions, Provider(), chat_id))
    response = client.get("/api/conversations/" + chat_id)
    if action == "delete":
        assert response.status_code == 404
    else:
        detail = response.json()
        assert detail["title"] == ("My manual title" if action == "rename" else "synthetic input")
        assert (
            detail["title_status"]
            == {"rename": "manual", "fail": "failed", "interrupt": "interrupted"}[action]
        )
        assert "PRIVATE_PROVIDER_FAILURE" not in response.text


def test_stalled_title_reconciliation_does_not_repeat_provider(setup):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    with app.state.sessions() as db:
        db.get(Conversation, chat_id).title_status = "running"
        db.commit()

    class Provider:
        async def title(self, *args):
            raise AssertionError("Interrupted inference must not repeat")

    asyncio.run(execute_title(app.state.sessions, Provider(), chat_id))
    assert client.get("/api/conversations/" + chat_id).json()["title_status"] == "interrupted"


@pytest.mark.parametrize("content", [
    "Passwort: synthetic-credential", "Bearer synthetic-access-value",
    "ssh-ed25519 synthetic-public-key", "x" * 50,
])
def test_secret_like_input_has_neutral_local_title_without_refinement(setup, content):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    with app.state.sessions() as db:
        db.add(Message(conversation_id=chat_id, role="user", content=content))
        db.flush()
        reserve_title(db, app.state.settings, chat_id)
        db.commit()

    class Offline:
        async def title(self, *args):
            raise AssertionError("Secret-like title must never need a model request")

    asyncio.run(execute_title(app.state.sessions, Offline(), chat_id))
    detail = client.get("/api/conversations/" + chat_id).json()
    assert detail["title"] == "Vertrauliche Anfrage"


def test_initial_title_is_bounded_and_removes_controls_urls_and_mail_addresses():
    assert initial_title("Welche Updates stehen in Home Assistant aus?") == (
        "Welche Updates stehen in Home Assistant aus?"
    )
    title = initial_title("## Test\x00 https://example.test/private user@example.test")
    assert title == "Test"
    assert len(initial_title("Ein langes Thema " * 30)) <= 76
    assert initial_title("\n\x00") == "Neue Anfrage"


def test_initial_title_never_replaces_manual_or_hidden_conversation(setup):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    client.patch("/api/conversations/" + chat_id, json={"title": "Eigener Titel"}, headers=headers)
    pending(app, chat_id)
    with app.state.sessions() as db:
        ensure_initial_title(db, chat_id)
        hidden = Conversation(purpose="agent", title="Neues Gespräch")
        db.add(hidden)
        db.flush()
        db.add(Message(conversation_id=hidden.id, role="user", content="Hidden synthetic prompt"))
        db.flush()
        ensure_initial_title(db, hidden.id)
        assert hidden.title == "Neues Gespräch"
        db.commit()
    assert client.get("/api/conversations/" + chat_id).json()["title"] == "Eigener Titel"
