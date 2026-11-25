"""Conversation detail exposes persisted archive state after reload, without inference."""

from test_chat import new_chat

pytest_plugins = ["test_chat"]


def test_detail_archive_reopen_and_send_protection_agree(setup):
    _, client, headers, provider = setup
    chat = new_chat(client, headers)
    path = f"/api/conversations/{chat}"
    assert client.get(path).json()["archived"] is False
    assert client.patch(path, headers=headers, json={"archived": True}).status_code == 200
    assert client.get(path).json()["archived"] is True
    assert any(row["id"] == chat for row in client.get("/api/conversations?archived=true").json())
    response = client.post(path + "/messages", headers=headers, json={"content": "Synthetic input"})
    assert response.status_code == 404
    assert not provider.stream_calls
    assert client.patch(path, headers=headers, json={"archived": False}).status_code == 200
    assert client.get(path).json()["archived"] is False
    assert not provider.stream_calls
