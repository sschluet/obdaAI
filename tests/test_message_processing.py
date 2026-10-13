import json
import uuid
from dataclasses import replace

import pytest
import test_chat
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.db import Conversation, Message, Run, RunEvent
from hub.routing import Route
from sqlalchemy import select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # Migrate a disposable database, then run configured synthetic model IDs.
    original = test_chat.setup.__wrapped__(tmp_path, monkeypatch)
    existing, _, _, _ = next(original)
    cfg = replace(
        existing.state.settings, local_model="demo/local-one", openrouter_model="demo/cloud-two"
    )
    app = create_app(cfg)
    provider = test_chat.FakeProviders()
    app.state.providers = provider
    try:
        with TestClient(app) as client:
            result = client.post(
                "/api/login",
                json={"password": "synthetic-test-password"},
                headers={"Origin": cfg.origin},
            )
            assert result.status_code == 200
            headers = {"Origin": cfg.origin, "X-CSRF-Token": result.json()["csrf"]}
            yield app, client, headers, provider
    finally:
        original.close()


def events(response, kind):
    parsed = []
    for block in response.text.replace("\r\n", "\n").split("\n\n"):
        lines = block.splitlines()
        if "event: " + kind in lines:
            parsed.extend(json.loads(line[6:]) for line in lines if line.startswith("data: "))
    return parsed


def test_each_answer_uses_exact_linked_run_after_model_selection_and_reload(setup):
    app, client, headers, provider = setup
    chat = test_chat.new_chat(client, headers, cloud=True)
    local = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Hallo"},
    )
    assert events(local, "provider")[0] == {
        "name": "local",
        "model": "demo/local-one",
        "model_used": True,
        "reason": "simple fixture",
    }
    first = client.get("/api/conversations/" + chat).json()["messages"][-1]
    assert first["processing"]["model"] == "demo/local-one"
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="cloud fixture")
    cloud = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Second cloud synthetic question"},
    )
    assert events(cloud, "provider")[0]["model"] == "demo/cloud-two"
    with TestClient(create_app(app.state.settings)) as reloaded:
        reloaded.cookies.update(client.cookies)
        answer = [
            m
            for m in reloaded.get("/api/conversations/" + chat).json()["messages"]
            if m["role"] == "assistant"
        ]
    assert [m["processing"]["provider"] for m in answer] == ["local", "openrouter"]
    assert [m["processing"]["model"] for m in answer] == ["demo/local-one", "demo/cloud-two"]
    assert len({m["processing"]["run_id"] for m in answer}) == 2
    assert answer[0]["processing"] == first["processing"]


def test_retry_links_replacement_answer_not_old_run_or_list_position(setup):
    app, client, headers, provider = setup
    chat = test_chat.new_chat(client, headers, cloud=True)
    client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Synthetic retry question"},
    )
    old = client.get("/api/conversations/" + chat).json()["messages"][-1]
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="retry cloud")
    response = client.post(
        f"/api/conversations/{chat}/retry", headers=headers, json={"request_id": str(uuid.uuid4())}
    )
    assert events(response, "provider")[0]["name"] == "openrouter"
    answer = client.get("/api/conversations/" + chat).json()["messages"][-1]
    assert answer["processing"]["provider"] == "openrouter"
    assert answer["processing"]["run_id"] != old["processing"]["run_id"]
    with app.state.sessions() as db:
        assert db.get(Message, old["id"]).active is False
        assert db.get(Message, old["id"]).run_id == old["processing"]["run_id"]


def test_builtin_guidance_reports_local_tool_answer_without_a_model(setup):
    app, client, headers, provider = setup
    provider.decision = Route(capabilities=["task"], model_class="cloud", reason="task guidance")
    chat = test_chat.new_chat(client, headers, cloud=True)
    response = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Prepare a synthetic task"},
    )
    assert provider.stream_calls == []
    metadata = events(response, "provider")[0]
    assert metadata["name"] == "local" and metadata["model"] is None
    assert metadata["model_used"] is False
    answer = client.get("/api/conversations/" + chat).json()["messages"][-1]
    assert answer["processing"]["model_used"] is False
    assert answer["processing"]["model"] is None


def test_legacy_and_cross_conversation_links_are_not_inferred_from_labels_or_order(setup):
    app, client, headers, provider = setup
    chat = test_chat.new_chat(client, headers, cloud=True)
    other = test_chat.new_chat(client, headers)
    with app.state.sessions() as db:
        run = Run(
            conversation_id=chat,
            status="succeeded",
            provider="openrouter",
            model="demo/old",
            answer_model_used=True,
        )
        unrelated = Run(
            conversation_id=other,
            status="succeeded",
            provider="local",
            model="demo/unrelated",
            answer_model_used=True,
        )
        db.add_all([run, unrelated])
        db.flush()
        db.add_all(
            [
                Message(
                    conversation_id=chat,
                    role="assistant",
                    content="Identical legacy answer",
                    label="CLOUD_ALLOWED",
                ),
                Message(
                    conversation_id=chat,
                    role="assistant",
                    content="Identical legacy answer",
                    label="LOCAL_ONLY",
                ),
                Message(
                    conversation_id=chat,
                    role="assistant",
                    content="Foreign run link",
                    run_id=unrelated.id,
                ),
            ]
        )
        db.commit()
    loaded = client.get("/api/conversations/" + chat).json()
    assert all(m["processing"] is None for m in loaded["messages"])


def test_failure_after_partial_answer_retains_actual_run_and_status(setup):
    app, client, headers, provider = setup

    async def partial(*args, **kwargs):
        yield "Partial synthetic answer"
        raise ValueError("synthetic upstream failure")

    provider.decision = Route(capabilities=["chat"], model_class="local", reason="partial")
    provider.stream = partial
    chat = test_chat.new_chat(client, headers)
    client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Partial synthetic question"},
    )
    answer = client.get("/api/conversations/" + chat).json()["messages"][-1]
    assert answer["processing"]["status"] == "failed"
    assert answer["processing"]["model"] == "demo/local-one"
    with app.state.sessions() as db:
        assert db.scalar(select(Run).where(Run.id == answer["processing"]["run_id"]))
        assert db.get(Conversation, chat)


def test_migration_backfills_only_unique_exact_event_proof_and_preserves_every_message(setup):
    from alembic import command
    from alembic.config import Config

    app, client, headers, provider = setup
    chat = test_chat.new_chat(client, headers)
    other = test_chat.new_chat(client, headers)
    with app.state.sessions() as db:
        messages = [
            Message(
                conversation_id=chat,
                role="assistant",
                content=content,
                label="CLOUD_ALLOWED",
                active=active,
            )
            for content, active in [
                ("Unique answer!", True),
                ("Repeated run", True),
                ("Repeated message", True),
                ("Repeated message", False),
                ("Without events", True),
                ("Other only", True),
                ("Malformed", True),
            ]
        ]
        db.add_all(messages)
        run_specs = [
            (chat, ["Unique ", "answer!"]),
            (chat, ["Repeated run"]),
            (chat, ["Repeated run"]),
            (chat, ["Repeated message"]),
            (chat, []),
            (other, ["Other only"]),
            (chat, ["Malformed", None]),
        ]
        identifiers = []
        for conversation, chunks in run_specs:
            run = Run(
                conversation_id=conversation,
                status="succeeded",
                provider="openrouter",
                model="demo/historical",
            )
            db.add(run)
            db.flush()
            identifiers.append(run.id)
            for sequence, chunk in enumerate(chunks, 1):
                db.add(
                    RunEvent(
                        run_id=run.id,
                        sequence=sequence,
                        kind="delta",
                        payload=json.dumps({"text": chunk}),
                    )
                )
        db.commit()
        before = {m.id: (m.content, m.label, m.active, m.revision, m.created) for m in messages}
    # Represent the pre-feature schema, then perform the actual migration.
    command.downgrade(Config("alembic.ini"), "0026")
    command.upgrade(Config("alembic.ini"), "0027")
    with app.state.sessions() as db:
        migrated = list(db.scalars(select(Message).where(Message.conversation_id == chat)))
        assert {
            m.id: (m.content, m.label, m.active, m.revision, m.created) for m in migrated
        } == before
        linked = [m for m in migrated if m.run_id]
        assert len(linked) == 1 and linked[0].run_id == identifiers[0]
        assert linked[0].content == "Unique answer!"
    # The current application reads the current schema, after checking the
    # isolated historical backfill at its original migration revision.
    command.upgrade(Config("alembic.ini"), "head")
    proof = client.get("/api/conversations/" + chat).json()["messages"][0]["processing"]
    assert proof["model"] == "demo/historical" and proof["model_used"] is None


def test_migration_downgrade_refuses_to_discard_provenance(setup):
    from alembic import command
    from alembic.config import Config

    app, client, headers, provider = setup
    chat = test_chat.new_chat(client, headers)
    client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Synthetic proven answer"},
    )
    with pytest.raises(RuntimeError, match="Preserve message processing provenance"):
        command.downgrade(Config("alembic.ini"), "0026")
