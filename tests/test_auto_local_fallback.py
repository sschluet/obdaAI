import json

import httpx
import pytest
from hub.db import Run
from sqlalchemy import select
from test_chat import new_chat

pytest_plugins = ["test_chat"]


@pytest.mark.parametrize("explicit,partial", [(False, False), (True, False), (False, True)])
def test_fallback_only_auto_before_first_answer(setup, explicit, partial):
    app, client, headers, provider = setup
    calls = []

    async def stream(parts, roles, *, external, grants):
        calls.append(external)
        if external:
            if partial:
                yield "CLOUD_PARTIAL"
            raise httpx.ConnectError("synthetic outage")
        yield "LOCAL_FALLBACK"

    provider.stream = stream
    chat = new_chat(client, headers)
    reply = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={
            "content": "Erstelle ein umfassendes Konzept für ein Serviceteam",
            "cloud_allowed": True,
            "model_cloud_only": explicit,
        },
    )
    if explicit or partial:
        assert calls == [True]
        assert "LOCAL_FALLBACK" not in reply.text
    else:
        assert calls == [True, False]
        assert "LOCAL_FALLBACK" in reply.text
        with app.state.sessions() as db:
            run = db.scalar(select(Run).where(Run.conversation_id == chat))
            assert run.provider == "local" and run.status == "succeeded"
            assert json.loads(run.routing_trace)["fallback"]["to"] == "local"


def test_provider_content_filter_never_falls_back(setup):
    from hub.budgets import ExecutionLimitError

    _, client, headers, provider = setup
    calls = []

    async def stream(parts, roles, *, external, grants):
        calls.append(external)
        raise ExecutionLimitError("synthetic content filter")
        yield "unreachable"

    provider.stream = stream
    chat = new_chat(client, headers)
    reply = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Erstelle eine komplexe Analyse", "cloud_allowed": True},
    )
    assert calls == [True]
    assert "synthetic content filter" in reply.text
