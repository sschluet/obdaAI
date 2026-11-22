"""A catalog/arithmetic probe cannot substitute for planner semantics."""

import json
import time
import uuid

import httpx
import pytest

pytest_plugins = ["test_provider_settings"]


@pytest.mark.parametrize("correct,tool_correct", [(True, True), (False, True), (True, False)])
def test_planner_probe_checks_local_schema_and_semantics(
    managed, monkeypatch, correct, tool_correct
):
    _, client, headers, _ = managed
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert body["enable_thinking"] is False
        assert body["temperature"] == 0
        assert body["response_format"]["type"] == "json_schema"
        assert body["max_tokens"] == 768
        assert "password" not in json.dumps(body).lower()
        intent = {
            "version": 1,
            "target_ids": ["synthetic-ha"],
            "mode": "observe",
            "topic": "inventory",
            "origin": "semantic",
            "answer_kind": "general",
            "research": False,
            "followup": False,
            "freshness": "current",
            "confidence": "certain",
            "requirements": [
                {
                    "kind": "entity_states",
                    "integration_id": "synthetic-ha",
                    "domain": "light" if correct else "sensor",
                }
            ],
        }
        if len(seen) == 2:
            assert correct
            intent = {
                "kind": "tool",
                "integration_id": "synthetic-ha",
                "tool": "http",
                "message": "Read actual states",
                "arguments": {"method": "GET", "path": "/api/states" if tool_correct else "/api/"},
            }
        text = json.dumps(intent)
        return httpx.Response(
            200,
            text="data: "
            + json.dumps({"choices": [{"delta": {"content": text}}]})
            + "\n\ndata: [DONE]\n\n",
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    body = {"mode": "planner", "request_id": str(uuid.uuid4())}
    result = client.post("/api/providers/local-default/test", headers=headers, json=body)
    assert result.status_code == 200
    for _ in range(100):
        probe = client.get("/api/provider-tests/" + body["request_id"]).json()
        if probe["status"] not in ("queued", "running"):
            break
        time.sleep(0.01)
    assert probe["status"] == ("succeeded" if correct and tool_correct else "failed")
    assert len(seen) == (2 if correct else 1)
    # Idempotent replay is bounded to the original check role.
    assert (
        client.post("/api/providers/local-default/test", headers=headers, json=body).status_code
        == 200
    )
    assert len(seen) == (2 if correct else 1)
    assert (
        client.post(
            "/api/providers/local-default/test", headers=headers, json={**body, "mode": "model"}
        ).status_code
        == 409
    )
    public = client.get("/api/providers").json()["providers"]
    assert next(p for p in public if p["id"] == "local-default")["last_test"]["mode"] == "planner"
