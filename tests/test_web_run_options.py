"""Per-run web choices survive retries without granting external model access."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
import test_chat
from hub.db import Message, Run
from hub.routing import Route
from sqlalchemy import select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def prepare(setup, monkeypatch, *, cloud=True):
    app, client, headers, provider = setup
    from hub.execution import execute_run

    cfg = replace(app.state.settings, search_url="https://synthetic-search.invalid/search")

    async def execute(factory, settings, providers, run_id):
        await execute_run(factory, cfg, providers, run_id)

    monkeypatch.setattr("hub.api.execute_run", execute)
    provider.decision = Route(capabilities=["chat", "web"], model_class="cloud", reason="Test")
    queries = []

    async def search(settings, request, *, options=None):
        assert request.public_query_approved
        queries.append(request.query)
        return [
            {
                "url": "https://example.org/source",
                "title": "Synthetic source",
                "content": "Synthetic fact",
                "retrieved_at": 1,
                "provider": "synthetic",
            }
        ]

    monkeypatch.setattr("hub.websearch.search", search)
    chat = test_chat.new_chat(client, headers, cloud=cloud)
    return app, client, headers, provider, queries, "/api/conversations/" + chat


def test_web_retry_edit_freezes_current_query_and_never_inherits_stale_query(setup, monkeypatch):
    app, client, headers, provider, queries, url = prepare(setup, monkeypatch)
    opts = {"web_search_allowed": True, "model_local_only": True}
    original = "Research synthetic topic alpha"
    sent = client.post(
        url + "/messages",
        headers=headers,
        json={**opts, "content": original, "web_query": "old explicit search"},
    )
    assert "succeeded" in sent.text
    retried = client.post(
        url + "/retry", headers=headers, json={**opts, "request_id": str(uuid4())}
    )
    assert "succeeded" in retried.text
    user = next(m for m in client.get(url).json()["messages"] if m["role"] == "user")
    edited = "Research synthetic topic beta"
    response = client.patch(
        url + "/messages/" + user["id"],
        headers=headers,
        json={**opts, "content": edited, "revision": user["revision"]},
    )
    assert "succeeded" in response.text
    again = client.post(url + "/retry", headers=headers, json={**opts, "request_id": str(uuid4())})
    assert "succeeded" in again.text
    assert queries == ["old explicit search", original, edited, edited]
    assert provider.stream_calls == [False] * 4
    with app.state.sessions() as db:
        assert db.get(Message, user["id"]).label == "LOCAL_ONLY"
        for run in db.scalars(select(Run)):
            snapshot = json.loads(run.context_snapshot)
            assert snapshot["model_local_only"]
            assert all(p["label"] == "LOCAL_ONLY" for p in snapshot["parts"])


def test_default_api_clients_still_do_not_authorize_web_and_explicit_local_blocks_it(
    setup, monkeypatch
):
    _, client, headers, _, queries, url = prepare(setup, monkeypatch)
    sent = client.post(
        url + "/messages",
        headers=headers,
        json={"content": "Research synthetic topic", "model_local_only": True},
    )
    assert "failed" in sent.text and queries == []
    retry = client.post(
        url + "/retry",
        headers=headers,
        json={"request_id": str(uuid4()), "local_only": True, "web_search_allowed": True},
    )
    assert retry.status_code == 422 and queries == []


def test_long_prompt_uses_bounded_query_not_private_chat_history(setup, monkeypatch):
    app, client, headers, _, queries, url = prepare(setup, monkeypatch)
    content = "Research " + "synthetic " * 80
    result = client.post(
        url + "/messages",
        headers=headers,
        json={"content": content, "web_search_allowed": True, "model_local_only": True},
    )
    assert "succeeded" in result.text
    assert queries == [content[:500]]
    with app.state.sessions() as db:
        snapshot = json.loads(db.scalar(select(Run)).context_snapshot)
        assert snapshot["web_query"] == content[:500]


def test_model_choice_and_web_query_are_idempotency_bound(setup, monkeypatch):
    _, client, headers, _, queries, url = prepare(setup, monkeypatch)
    body = {
        "content": "Research synthetic topic",
        "model_local_only": True,
        "web_search_allowed": True,
        "web_query": "public topic",
        "request_id": str(uuid4()),
    }
    assert "succeeded" in client.post(url + "/messages", headers=headers, json=body).text
    for change in ({"model_local_only": False}, {"web_query": "other public topic"}):
        assert (
            client.post(url + "/messages", headers=headers, json={**body, **change}).status_code
            == 409
        )
    assert queries == ["public topic"]


def test_force_local_model_blocks_cloud_even_without_web_and_on_retry(setup):
    app, client, headers, provider = setup
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="Cloud fixture")
    chat = test_chat.new_chat(client, headers, cloud=True)
    url = "/api/conversations/" + chat
    assert (
        "succeeded"
        in client.post(
            url + "/messages", headers=headers, json={"content": "Public synthetic topic"}
        ).text
    )
    assert provider.stream_calls == [True]
    assert (
        "succeeded"
        in client.post(
            url + "/retry",
            headers=headers,
            json={"model_local_only": True, "request_id": str(uuid4())},
        ).text
    )
    assert provider.stream_calls == [True, False]
    with app.state.sessions() as db:
        assert db.scalar(select(Message).where(Message.role == "user")).label == "CLOUD_ALLOWED"
        latest = db.scalar(select(Run).order_by(Run.started.desc()))
        snapshot = json.loads(latest.context_snapshot)
        assert snapshot["model_local_only"]
        assert all(p["label"] == "LOCAL_ONLY" for p in snapshot["parts"])
    assert (
        "succeeded"
        in client.post(
            url + "/messages",
            headers=headers,
            json={"content": "Synthetic local model topic", "model_local_only": True},
        ).text
    )
    assert provider.stream_calls == [True, False, False]
    with app.state.sessions() as db:
        latest_user = db.scalar(
            select(Message).where(Message.role == "user").order_by(Message.created.desc())
        )
        assert latest_user.label == "LOCAL_ONLY"
