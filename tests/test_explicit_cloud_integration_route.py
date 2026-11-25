"""Explicit Cloud does not await local classification or acquire private tools."""

from hub.agent_models import AgentJob
from sqlalchemy import select
from test_integration_routing import standalone

pytest_plugins = ["test_integration_routing"]


def test_explicit_cloud_ordinary_request_routes_without_local_model_dependency(agent, monkeypatch):
    app, client, headers, *_ = agent
    chat = standalone(agent)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Explicit Cloud must not invoke local interpretation")

    monkeypatch.setattr("hub.request_interpretation.interpret", forbidden)
    response = client.post(f"/api/conversations/{chat}/integration-route", headers=headers,
                           json={"goal": "Entwickle bitte ein ausführliches Konzept für "
                                 "einen öffentlichen Vortrag über Astronomie.",
                                 "model_mode": "cloud"})
    assert response.status_code == 200 and response.json() == {
        "route": "chat", "integration_ids": [],
    }
    with app.state.sessions() as db:
        assert db.scalar(select(AgentJob.id).where(AgentJob.conversation_id == chat)) is None


def test_explicit_cloud_keeps_lexical_private_target_signal_without_dispatch(agent, monkeypatch):
    app, client, headers, *_ = agent
    chat = standalone(agent)

    async def forbidden(*args, **kwargs):
        raise AssertionError("No local inference or private tool access during routing")

    monkeypatch.setattr("hub.request_interpretation.interpret", forbidden)
    response = client.post(f"/api/conversations/{chat}/integration-route", headers=headers,
                           json={"goal": "Zeige meine Dokumente in Paperless.",
                                 "model_mode": "cloud"})
    assert response.status_code == 200 and response.json()["route"] == "agent"
    assert response.json()["integration_ids"] == [agent[4]]
    with app.state.sessions() as db:
        assert db.scalar(select(AgentJob.id).where(AgentJob.conversation_id == chat)) is None
