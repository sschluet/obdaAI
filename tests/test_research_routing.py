"""Text research narrows erroneous action classifications without granting egress."""

import json
from dataclasses import replace

import pytest
import test_chat
from hub.db import Artifact, Research, Run, Task
from hub.routing import Capability, Route, conversational_research
from sqlalchemy import func, select

GOAL = (
    "Erstelle eine komplexe Recherche zum Thema Managed Services in der Zukunft "
    "vor dem Hintergrund AI und den aktuellen Entwicklungen"
)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def incorrect_route():
    return Route(
        capabilities=["web", "retrieval", "artifact", "task", "workflow", "tool"],
        model_class="cloud",
        read_tool="hub.inspect",
        reason="Overclassified fixture",
    )


@pytest.mark.parametrize(
    "goal",
    [
        GOAL,
        "Bitte erarbeite eine umfassende Analyse über die Zukunft von Workflows.",
        "Research managed services and future automation trends.",
    ],
)
def test_future_workflow_topics_are_text_research(goal):
    original = incorrect_route()
    result = conversational_research(original, goal, private_context=False)
    assert result.capabilities == [Capability.CHAT, Capability.WEB]
    assert result.read_tool is None and result.answer is None
    assert result.model_class == "cloud"
    assert original.capabilities == incorrect_route().capabilities
    scoped = conversational_research(original, goal, private_context=True)
    assert scoped.capabilities == [Capability.CHAT, Capability.WEB, Capability.RETRIEVAL]


@pytest.mark.parametrize(
    "goal",
    [
        GOAL + " als Word-Datei.",
        GOAL + " und erstelle einen Workflow.",
        GOAL + " und aktiviere eine Aufgabe.",
        "Recherchiere AI und prüfe Home Assistant.",
        "Research AI and delete a file.",
        "Recherchiere AI und aktualisiere Home Assistant.",
        "Research AI and start a workflow.",
        "Research AI and use hub.inspect.",
        "Research budget.xlsx.",
        GOAL + " als Aufgabe.",
        GOAL + " jeden Montag.",
        "Research AI and schedule a reminder.",
        "Recherchiere aus meinen Dokumenten.",
        "Erstelle eine Recherche aus den Projektunterlagen.",
        "Erstelle eine PDF-Datei zur Zukunft von AI.",
        "Erstelle einen automatisierten Rechercheworkflow.",
    ],
)
def test_explicit_files_sources_and_actions_keep_all_execution_gates(goal):
    original = incorrect_route()
    assert conversational_research(original, goal, private_context=False) is original


@pytest.mark.parametrize("approved", [False, True])
def test_misclassified_research_streams_text_only_after_explicit_web_approval(
    setup, monkeypatch, approved
):
    app, client, headers, provider = setup
    provider.decision = incorrect_route()
    from hub.execution import execute_run

    settings = replace(app.state.settings, search_url="https://synthetic-search.invalid/search")

    async def execute(factory, cfg, providers, run_id):
        await execute_run(factory, settings, providers, run_id)

    monkeypatch.setattr("hub.api.execute_run", execute)
    queries = []

    async def search(cfg, request):
        assert request.public_query_approved
        queries.append(request.query)
        return [
            {
                "url": "https://example.org/research",
                "title": "Synthetic source",
                "content": "Synthetic research evidence.",
                "retrieved_at": 1,
                "provider": "synthetic",
            }
        ]

    monkeypatch.setattr("hub.websearch.search", search)
    chat = test_chat.new_chat(client, headers)
    response = client.post(
        "/api/conversations/" + chat + "/messages",
        headers=headers,
        json={"content": GOAL, "web_search_allowed": approved},
    )
    assert "Dateierstellung bitte getrennt" not in response.text
    if approved:
        assert "succeeded" in response.text
        detail = client.get("/api/conversations/" + chat).json()
        assert detail["messages"][-1]["content"] == "SYNTHETIC_STREAM"
        assert queries == [GOAL] and provider.stream_calls == [False]
    else:
        assert "ausdrücklich für die Websuche bestätigen" in response.text
        assert "failed" in response.text and queries == [] and provider.stream_calls == []
    with app.state.sessions() as db:
        run = db.scalar(select(Run))
        assert json.loads(run.capabilities) == ["chat", "web"]
        assert db.scalar(select(func.count()).select_from(Artifact)) == 0
        assert db.scalar(select(func.count()).select_from(Task)) == 0
        assert db.scalar(select(func.count()).select_from(Research)) == int(approved)
        assert "tool_reads" not in json.loads(run.context_snapshot)


@pytest.mark.parametrize("cloud", [False, True])
def test_text_research_does_not_invent_web_or_cloud_permission(setup, cloud):
    app, client, headers, provider = setup
    provider.decision = Route(
        capabilities=["artifact", "task", "workflow"],
        model_class="cloud",
        reason="Incorrect action fixture",
    )
    chat = test_chat.new_chat(client, headers, cloud)
    response = client.post(
        "/api/conversations/" + chat + "/messages",
        headers=headers,
        json={"content": GOAL},
    )
    assert "succeeded" in response.text
    assert provider.stream_calls == [cloud]
    with app.state.sessions() as db:
        run = db.scalar(select(Run))
        assert json.loads(run.capabilities) == ["chat"]
        assert db.scalar(select(func.count()).select_from(Artifact)) == 0
        assert db.scalar(select(func.count()).select_from(Task)) == 0
        assert db.scalar(select(func.count()).select_from(Research)) == 0
