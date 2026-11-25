"""Semantic routing is local data interpretation, bound to current selected targets."""

import json
from uuid import uuid4

import pytest
from hub.agent_intent import RequestIntent, Requirement
from hub.agent_models import AgentJob
from hub.integrations import Integration
from sqlalchemy import select
from test_integration_routing import route, standalone

pytest_plugins = ["test_integration_routing"]


@pytest.mark.parametrize("revoke", [False, True])
def test_semantic_route_binds_current_signature_and_freezes_intent(agent, monkeypatch, revoke):
    app, client, headers, *_ = agent
    chat = standalone(agent)
    identifier = agent[4]
    seen = []
    goal = "Ich benötige bitte einen Überblick über die offenen Unterlagen."

    async def interpret(
        factory, cfg, text, profiles, *, prior_target_ids=None, conversation_id=None
    ):
        assert text == goal and identifier in profiles
        seen.append(True)
        if revoke:
            with factory() as db:
                profile = db.get(Integration, identifier)
                profile.revision += 1
                db.commit()
        return RequestIntent(
            target_ids=[identifier],
            mode="observe",
            topic="documents",
            origin="semantic",
            requirements=[Requirement(kind="documents", integration_id=identifier)],
        )

    monkeypatch.setattr("hub.request_interpretation.interpret", interpret)
    result = route(agent, chat, goal)
    assert seen == [True]
    if revoke:
        assert result.status_code == 409
        return
    assert result.json() == {"route": "agent", "integration_ids": [identifier]}
    started = client.post(
        f"/api/conversations/{chat}/agent-runs",
        headers=headers,
        json={"request_id": str(uuid4()), "goal": goal, "integration_ids": [identifier]},
    )
    assert started.status_code == 200, started.text
    with app.state.sessions() as db:
        job = db.get(AgentJob, started.json()["id"])
        frozen = json.loads(job.bindings)
        assert frozen["intent"]["origin"] == "semantic"
        assert frozen["read_only"] is True and job.max_effects == 0
    assert len(seen) == 1


def test_semantic_failure_preserves_authority_and_reports_degradation(agent, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise TimeoutError("Synthetic unavailable model")

    monkeypatch.setattr("hub.request_interpretation.interpret", unavailable)
    chat = standalone(agent)
    response = route(agent, chat, "Ich benötige bitte einen Überblick über die offenen Unterlagen.")
    assert response.status_code == 503
    assert agent[0].state.intent_interpretation_degraded is True
    # No job and no remote target request was dispatched by the route classifier.
    with agent[0].state.sessions() as db:
        assert db.scalar(select(AgentJob.id).where(AgentJob.conversation_id == chat)) is None


def test_reference_change_during_interpretation_invalidates_route_even_with_same_target(
    agent, monkeypatch
):
    identifier = agent[4]
    state = {"revision": 1}

    def references(*args):
        return [
            {
                "content": json.dumps(
                    {"integration_id": identifier, "receipt_revision": state["revision"]}
                )
            }
        ]

    async def classify(*args, **kwargs):
        assert kwargs["prior_target_ids"] == [identifier]
        state["revision"] = 2
        return RequestIntent(
            mode="observe",
            topic="documents",
            target_ids=[identifier],
            requirements=[Requirement(kind="documents", integration_id=identifier)],
        )

    monkeypatch.setattr("hub.agent_read_references.previous_references", references)
    monkeypatch.setattr("hub.request_interpretation.interpret", classify)
    response = route(
        agent, standalone(agent), "Ich benötige einen Überblick der offenen Unterlagen."
    )
    assert response.status_code == 409
    with agent[0].state.sessions() as db:
        assert db.scalar(select(AgentJob.id)) is None
