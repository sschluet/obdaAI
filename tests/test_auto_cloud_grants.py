"""Explicit Auto grants for ordinary current inputs; historical privacy remains intact."""

import uuid

from hub.routing import Route
from test_chat import new_chat

pytest_plugins = ["test_chat"]


def test_auto_grants_current_message_in_existing_empty_chat(setup):
    _, client, headers, provider = setup
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="complex")
    chat_id = new_chat(client, headers)
    response = client.post(
        f"/api/conversations/{chat_id}/messages",
        headers=headers,
        json={
            "content": "Synthetic analysis",
            "cloud_allowed": True,
            "cloud_provider": "openrouter",
        },
    )
    assert response.status_code == 200
    assert provider.stream_calls == [True]
    detail = client.get(f"/api/conversations/{chat_id}").json()
    assert detail["cloud_allowed"] is True
    assert all(m["label"] == "CLOUD_ALLOWED" for m in detail["messages"])


def test_auto_preserves_previous_local_only_history(setup):
    _, client, headers, provider = setup
    chat_id = new_chat(client, headers)
    client.post(
        f"/api/conversations/{chat_id}/messages",
        headers=headers,
        json={"content": "Synthetic confidential history"},
    )
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="complex")
    client.post(
        f"/api/conversations/{chat_id}/messages",
        headers=headers,
        json={"content": "Synthetic new analysis", "cloud_allowed": True},
    )
    detail = client.get(f"/api/conversations/{chat_id}").json()
    assert detail["messages"][0]["label"] == "LOCAL_ONLY"
    assert detail["messages"][2]["label"] == "CLOUD_ALLOWED"
    assert provider.stream_calls == [False]


def test_auto_retry_can_grant_only_current_input(setup):
    _, client, headers, provider = setup
    chat_id = new_chat(client, headers)
    client.post(
        f"/api/conversations/{chat_id}/messages",
        headers=headers,
        json={"content": "Synthetic question"},
    )
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="complex")
    response = client.post(
        f"/api/conversations/{chat_id}/retry",
        headers=headers,
        json={"cloud_allowed": True, "request_id": str(uuid.uuid4())},
    )
    assert response.status_code == 200
    detail = client.get(f"/api/conversations/{chat_id}").json()
    assert detail["messages"][0]["label"] == "CLOUD_ALLOWED"
    assert provider.stream_calls == [True]


def test_explicit_cloud_off_overrides_granted_chat(setup):
    _, client, headers, provider = setup
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="complex")
    chat_id = new_chat(client, headers, cloud=True)
    client.post(
        f"/api/conversations/{chat_id}/messages",
        headers=headers,
        json={"content": "Synthetic local question", "cloud_allowed": False},
    )
    assert provider.stream_calls == [False]
    detail = client.get(f"/api/conversations/{chat_id}").json()
    assert all(m["label"] == "LOCAL_ONLY" for m in detail["messages"])


def test_auto_grant_is_action_bound_for_idempotency(setup):
    _, client, headers, _ = setup
    chat_id = new_chat(client, headers)
    key = str(uuid.uuid4())
    body = {"content": "Synthetic question", "request_id": key, "cloud_allowed": True}
    first = client.post(f"/api/conversations/{chat_id}/messages", headers=headers, json=body)
    assert first.status_code == 200
    assert (
        client.post(
            f"/api/conversations/{chat_id}/messages",
            headers=headers,
            json={**body, "cloud_allowed": False},
        ).status_code
        == 409
    )


def test_private_memory_chat_rejects_auto_cloud_grant(setup):
    _, client, headers, _ = setup
    created = client.post("/api/conversations", headers=headers, json={"memory_scope": "global"})
    assert created.status_code == 200
    chat_id = created.json()["id"]
    response = client.post(
        f"/api/conversations/{chat_id}/messages",
        headers=headers,
        json={"content": "Synthetic private question", "cloud_allowed": True},
    )
    assert response.status_code == 409
    assert client.get(f"/api/conversations/{chat_id}").json()["messages"] == []
