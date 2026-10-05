import json

import pytest
import test_chat
from fastapi import HTTPException
from hub import chat_tools
from hub.budgets import ExecutionLimitError
from hub.db import ActionReceipt, Run
from hub.routing import Route
from pydantic import ValidationError
from sqlalchemy import select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def test_ha_chat_read_stays_local_and_has_durable_receipt(setup, monkeypatch):
    app, c, h, provider = setup
    calls = []

    def inspect(cfg):
        calls.append(True)
        return {"version": "2026.9.3", "writes_enabled": False, "private": "OMITTED"}

    monkeypatch.setattr(chat_tools, "health", inspect)
    provider.decision = Route(
        capabilities=["tool"], model_class="cloud", reason="HA read", read_tool="ha.inspect"
    )
    chat = test_chat.new_chat(c, h, cloud=True)
    r = c.post(f"/api/conversations/{chat}/messages", headers=h, json={"content": "HA Status"})
    assert r.status_code == 200 and "succeeded" in r.text and "SYNTHETIC_" in r.text
    assert provider.stream_calls == [False] and len(calls) == 1
    with app.state.sessions() as db:
        run = db.scalar(select(Run))
        snapshot = json.loads(run.context_snapshot)
        proof = snapshot["tool_reads"][0]
        assert proof["tool_id"] == "ha.inspect" and proof["label"] == "LOCAL_ONLY"
        part = snapshot["parts"][-1]
        assert part["label"] == "LOCAL_ONLY" and "OMITTED" not in part["content"]
        assert db.get(ActionReceipt, proof["action_id"])
        run_id = run.id
    chat_tools.read(app.state.sessions, app.state.settings, run_id, "ha.inspect")
    assert len(calls) == 1
    with pytest.raises(ExecutionLimitError, match="geändert"):
        chat_tools.read(app.state.sessions, app.state.settings, run_id, "hub.inspect")


def test_unavailable_ha_is_error_without_cloud_or_fabricated_report(setup, monkeypatch):
    app, c, h, provider = setup

    def unavailable(cfg):
        raise HTTPException(503, "INTERNAL_SECRET")

    monkeypatch.setattr(chat_tools, "health", unavailable)
    provider.decision = Route(
        capabilities=["tool"], model_class="cloud", reason="HA read", read_tool="ha.inspect"
    )
    chat = test_chat.new_chat(c, h, cloud=True)
    r = c.post(f"/api/conversations/{chat}/messages", headers=h, json={"content": "HA Status"})
    assert "INTERNAL_SECRET" not in r.text and "error" in r.text
    assert provider.stream_calls == []
    with app.state.sessions() as db:
        assert db.scalar(select(ActionReceipt)) is None


@pytest.mark.parametrize("selector", ["ha.update", "https://host/", "shell", "mcp.read"])
def test_router_rejects_unbounded_selector(selector):
    with pytest.raises(ValidationError):
        Route(capabilities=["tool"], model_class="local", reason="test", read_tool=selector)


def test_selector_requires_tool_capability():
    with pytest.raises(ValidationError):
        Route(capabilities=["chat"], model_class="local", reason="test", read_tool="ha.inspect")
