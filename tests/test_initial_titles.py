"""First-message titles survive model outages and unexecuted agent jobs."""

from hub.db import Conversation, Message
from test_agent_capability_runtime import start
from test_chat import new_chat

pytest_plugins = ["test_chat", "test_agent_capability_runtime"]


def test_first_ordinary_input_has_persisted_title_when_local_model_is_offline(setup):
    app, client, headers, provider = setup
    provider.fail = True
    chat = new_chat(client, headers)
    goal = "Welche Unterlagen brauche ich für die synthetische Migration?"
    response = client.post(
        f"/api/conversations/{chat}/messages", json={"content": goal}, headers=headers,
    )
    assert response.status_code == 200
    detail = client.get(f"/api/conversations/{chat}").json()
    assert detail["title"] == goal
    assert detail["runs"][-1]["status"] == "failed"
    assert provider.stream_calls == []
    with app.state.sessions() as db:
        assert db.get(Conversation, chat).title == goal


def test_agent_first_input_has_title_before_any_model_or_target_execution(ha):
    app, client, headers, _, _, chat, _, effects = ha
    goal = "Welche Updates stehen in Home Assistant aus?"
    job = start(ha, goal, research_allowed=False)
    result = client.get("/api/agent-runs/" + job).json()
    assert result["status"] == "queued" and result["steps"] == []
    assert client.get(f"/api/conversations/{chat}").json()["title"] == goal
    assert not effects
    # Manual renaming wins even when explicitly choosing the original placeholder.
    client.patch(f"/api/conversations/{chat}", json={"title": "Neues Gespräch"}, headers=headers)
    with app.state.sessions() as db:
        from hub.titles import ensure_initial_title

        ensure_initial_title(db, chat)
        db.commit()
    assert client.get(f"/api/conversations/{chat}").json()["title"] == "Neues Gespräch"


def test_legacy_failed_placeholders_repair_on_listing_without_retry_or_manual_changes(setup):
    app, client, headers, provider = setup
    first = new_chat(client, headers)
    manual = new_chat(client, headers)
    hidden = new_chat(client, headers)
    with app.state.sessions() as db:
        for identifier in (first, manual, hidden):
            chat = db.get(Conversation, identifier)
            chat.title_status = "failed"
            db.add(Message(conversation_id=identifier, role="user", content="Migration planen"))
        db.get(Conversation, manual).manual_title = True
        db.get(Conversation, hidden).purpose = "agent"
        db.commit()
    rows = client.get("/api/conversations").json()
    repaired = next(row for row in rows if row["id"] == first)
    assert repaired["title"] == "Migration planen" and repaired["title_status"] == "failed"
    assert next(row for row in rows if row["id"] == manual)["title"] == "Neues Gespräch"
    assert all(row["id"] != hidden for row in rows)
    with app.state.sessions() as db:
        assert db.get(Conversation, first).title == "Migration planen"
        assert db.get(Conversation, hidden).title == "Neues Gespräch"
    assert provider.calls == 0 and provider.stream_calls == []
