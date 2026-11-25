"""A queued local send must recheck the run and its selected provider."""

import asyncio
from dataclasses import replace

import pytest
import test_chat
from hub.db import ProviderConfig, Run
from hub.provider_settings import seed
from hub.providers import Providers
from hub.routing import Route
from sqlalchemy import select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


@pytest.mark.parametrize("phase", ["route", "answer"])
@pytest.mark.parametrize("change", ["disabled", "revision", "cancelled"])
def test_queued_chat_rechecks_before_model_send(setup, monkeypatch, phase, change):
    app, client, headers, _ = setup
    cfg = replace(app.state.settings, local_model="synthetic", cloud_enabled=False)
    with app.state.sessions() as db:
        seed(db, cfg)
        row = db.get(ProviderConfig, "local-default")
        db.commit()
    sends = []

    class QueuedProvider(Providers):
        async def after_wait(self, role):
            await asyncio.sleep(0)
            if role == phase:
                with app.state.sessions() as db:
                    if change == "cancelled":
                        db.scalar(select(Run).where(Run.status.in_(["routing", "streaming"]))
                                  ).cancel_requested = True
                    else:
                        actual = db.get(ProviderConfig, row.id)
                        if change == "disabled":
                            actual.enabled = False
                        else:
                            actual.revision += 1
                    db.commit()
            assert self.before_send is not None
            self.before_send()
            sends.append(role)

        async def route(self, parts, roles):
            await self.after_wait("route")
            return Route(capabilities=["chat"], model_class="local", reason="Synthetic route")

        async def stream(self, *args, **kwargs):
            await self.after_wait("answer")
            yield "Must never escape the revoked answer boundary"

    provider = QueuedProvider(cfg)
    app.state.providers = provider
    monkeypatch.setattr(
        "hub.execution.runtime_provider", lambda *args, **kwargs: (cfg, provider, {"local": row})
    )
    chat_id = test_chat.new_chat(client, headers)
    response = client.post(
        f"/api/conversations/{chat_id}/messages",
        json={"content": "Synthetic ordinary question"}, headers=headers,
    )
    assert response.status_code == 200
    detail = client.get("/api/conversations/" + chat_id).json()
    assert detail["runs"][-1]["status"] == ("cancelled" if change == "cancelled" else "failed")
    assert sends == ([] if phase == "route" else ["route"])
    assert "Must never escape" not in response.text
    assert not any(message["role"] == "assistant" for message in detail["messages"])
