"""Durable execution contracts, synthetic content only."""

import asyncio
import json

from hub.db import Message, Run, RunEvent
from hub.execution import execute_run
from hub.routing import Route
from sqlalchemy import select
from test_chat import FakeProviders, new_chat

pytest_plugins = ["test_chat"]


def test_replay_cursor_auth_and_content_search(setup):
    app, client, headers, provider = setup
    chat_id = new_chat(client, headers)
    client.post(
        f"/api/conversations/{chat_id}/messages",
        json={"content": "unique_search_fixture"},
        headers=headers,
    )
    detail = client.get("/api/conversations/" + chat_id).json()
    run_id = detail["runs"][0]["id"]
    replay = client.get(f"/api/runs/{run_id}/events")
    assert "SYNTHETIC_ANSWER" in replay.text
    assert "event: done" in replay.text
    with app.state.sessions() as db:
        deltas = db.scalars(
            select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.kind == "delta")
        ).all()
        cursor = deltas[-1].sequence
    suffix = client.get(f"/api/runs/{run_id}/events?after={cursor}")
    assert "SYNTHETIC_ANSWER" not in suffix.text
    assert "event: done" in suffix.text
    assert client.get("/api/conversations?q=unique_search_fixture").json()[0]["id"] == chat_id
    assert client.get("/api/conversations?q=%25").json() == []
    client.post("/api/logout", headers=headers)
    assert client.get(f"/api/runs/{run_id}/events").status_code == 401


def test_queued_cancellation_and_duplicate_execution(setup):
    app, client, headers, provider = setup
    chat_id = new_chat(client, headers)
    with app.state.sessions() as db:
        run = Run(conversation_id=chat_id, status="queued", cancel_requested=True)
        db.add(run)
        db.add(Message(conversation_id=chat_id, role="user", content="fixture"))
        db.commit()
        run_id = run.id

    async def execute():
        await execute_run(app.state.sessions, app.state.settings, provider, run_id)
        await execute_run(app.state.sessions, app.state.settings, provider, run_id)

    asyncio.run(execute())
    assert provider.calls == 0
    assert client.get("/api/conversations/" + chat_id).json()["runs"][0]["status"] == "cancelled"


def test_execution_survives_display_disconnect_and_preserves_partial(setup):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)

    class Partial(FakeProviders):
        async def stream(self, *args, **kwargs):
            yield "SYNTHETIC_PARTIAL"
            raise ValueError("PRIVATE_ERROR")

    provider = Partial(Route(capabilities=["chat"], model_class="local", reason="fixture"))
    with app.state.sessions() as db:
        run = Run(conversation_id=chat_id, status="queued")
        db.add(run)
        db.add(Message(conversation_id=chat_id, role="user", content="fixture"))
        db.commit()
        run_id = run.id
    # Execute with no HTTP request or browser attached at all.
    asyncio.run(execute_run(app.state.sessions, app.state.settings, provider, run_id))
    detail = client.get("/api/conversations/" + chat_id).json()
    assert detail["runs"][0]["status"] == "failed"
    assert detail["messages"][-1]["content"] == "SYNTHETIC_PARTIAL"
    with app.state.sessions() as db:
        events = db.scalars(select(RunEvent).where(RunEvent.run_id == run_id)).all()
        assert any(json.loads(e.payload).get("text") == "SYNTHETIC_PARTIAL" for e in events)
    assert "PRIVATE_ERROR" not in client.get(f"/api/runs/{run_id}/events").text


def test_cancel_interrupts_pending_provider_without_browser(setup):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    entered = asyncio.Event()

    class Waiting(FakeProviders):
        async def route(self, parts, roles):
            entered.set()
            await asyncio.sleep(60)
            raise AssertionError("Cancellation did not interrupt provider")

    provider = Waiting()
    with app.state.sessions() as db:
        run = Run(conversation_id=chat_id, status="queued")
        db.add(run)
        db.add(Message(conversation_id=chat_id, role="user", content="fixture"))
        db.commit()
        run_id = run.id

    async def cancel_pending():
        task = asyncio.create_task(
            execute_run(app.state.sessions, app.state.settings, provider, run_id)
        )
        await entered.wait()
        with app.state.sessions() as db:
            current = db.get(Run, run_id)
            current.cancel_requested = True
            db.commit()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(cancel_pending())
    assert client.get("/api/conversations/" + chat_id).json()["runs"][0]["status"] == "cancelled"


def test_queued_run_blocks_second_message_and_delete(setup):
    app, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    with app.state.sessions() as db:
        db.add(Run(conversation_id=chat_id, status="queued"))
        db.commit()
    assert (
        client.post(
            f"/api/conversations/{chat_id}/messages", json={"content": "fixture"}, headers=headers
        ).status_code
        == 409
    )
    assert client.delete("/api/conversations/" + chat_id, headers=headers).status_code == 409
    assert client.get("/api/conversations/" + chat_id).json()["messages"] == []
