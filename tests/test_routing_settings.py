import asyncio
import json

import pytest
from hub.db import Run
from hub.routing_settings import RoutingOptions, decision
from sqlalchemy import select

pytest_plugins = ["test_chat"]

PROMPT = ("Erstelle eine komplexe Recherche zum Thema Managed Services in der Zukunft "
          "vor dem Hintergrund AI und den aktuellen Entwicklungen")


def choose(**changes):
    args = dict(classifier="local", cloud_enabled=True, cloud_allowed=True,
                model_local_only=False, private_context=False)
    args.update(changes)
    return decision(PROMPT, {"revision": 3, **RoutingOptions().model_dump()}, **args)


def test_balanced_complex_research_cloud_and_simple_chat_local():
    trace = choose()
    assert trace["effective_model_class"] == "cloud"
    assert trace["classifier_model_class"] == "local" and trace["policy_revision"] == 3
    assert trace["complexity"] == "complex" and not trace["blockers"]
    simple = decision("Hallo", RoutingOptions().model_dump(), classifier="local",
                      cloud_enabled=True, cloud_allowed=True, model_local_only=False,
                      private_context=False)
    assert simple["effective_model_class"] == "local"


@pytest.mark.parametrize("override", [dict(model_local_only=True), dict(cloud_enabled=False),
                                     dict(cloud_allowed=False), dict(private_context=True),
                                     dict(private_parts=True), dict(builtin=True)])
def test_privacy_blocks_policy_cloud(override):
    trace = choose(**override)
    assert trace["policy_model_class"] == "cloud" or override.get("builtin")
    assert trace["effective_model_class"] == "local" and trace["blockers"]


def test_strategy_and_switch_choices():
    args = dict(classifier="local", cloud_enabled=True, cloud_allowed=True,
                model_local_only=False, private_context=False)
    assert decision(PROMPT, {"strategy": "local_first"}, **args)["policy_model_class"] == "local"
    assert decision(PROMPT, {"strategy": "balanced", "complex_research_cloud": False},
                    **args)["policy_model_class"] == "local"
    assert decision("Hallo", {"strategy": "cloud_first"}, **args)["policy_model_class"] == "cloud"


def test_settings_cas_csrf_preview_no_provider(setup, monkeypatch):
    _, client, headers, provider = setup

    async def forbidden(*args, **kwargs):
        raise AssertionError("dryrun must not contact model")

    monkeypatch.setattr(provider, "route", forbidden)
    original = client.get("/api/routing-settings").json()
    assert original["strategy"] == "balanced" and original["revision"] == 0
    body = dict(revision=0, strategy="cloud_first", complex_research_cloud=True)
    assert client.put("/api/routing-settings", headers={"Origin": "http://testserver"},
                      json=body).status_code == 403
    saved = client.put("/api/routing-settings", headers=headers, json=body)
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    assert client.put("/api/routing-settings", headers=headers, json=body).status_code == 409
    assert client.put("/api/routing-settings", headers=headers,
                      json={**body, "strategy": "unknown"}).status_code == 422
    trace = client.post("/api/routing-settings/preview", headers=headers,
                        json={"prompt": PROMPT, "model_local_only": True}).json()
    assert trace["classifier_model_class"] is None and trace["preview"]
    assert trace["policy_revision"] == 1 and trace["effective_model_class"] == "local"


def test_policy_frozen_and_trace_persisted(setup, monkeypatch):
    app, client, headers, _ = setup
    from hub.execution import execute_run

    async def noop(factory, cfg, providers, run_id):
        with factory() as db:
            db.get(Run, run_id).status = "succeeded"
            db.commit()

    monkeypatch.setattr("hub.api.execute_run", noop)
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    result = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                         json={"content": PROMPT})
    assert result.status_code == 200
    with app.state.sessions() as db:
        run = db.scalar(select(Run))
        assert json.loads(run.context_snapshot)["routing_options"]["strategy"] == "balanced"
        run_id = run.id
        run.status = "queued"
        db.commit()
    client.put("/api/routing-settings", headers=headers,
               json={"revision": 0, "strategy": "local_first", "complex_research_cloud": True})
    asyncio.run(execute_run(app.state.sessions, app.state.settings, app.state.providers, run_id))
    trace = client.get(f"/api/runs/{run_id}").json()["routing"]
    assert trace["strategy"] == "balanced" and trace["policy_revision"] == 0
    assert trace["policy_model_class"] == "cloud" and trace["effective_model_class"] == "local"
    assert trace["actual_provider"] == "local"
    messages = client.get(f"/api/conversations/{chat}").json()["messages"]
    assert messages[-1]["processing"]["routing"] == trace


def test_explicit_cloud_scope_covers_public_search_results_only(setup, monkeypatch):
    from dataclasses import replace

    from hub.execution import execute_run
    from hub.routing import Route

    app, client, headers, provider = setup
    cfg = replace(app.state.settings, search_url="https://synthetic-search.invalid/search")

    async def execute(factory, settings, providers, run_id):
        await execute_run(factory, cfg, providers, run_id)

    async def search(settings, request, *, options):
        return [{"url": "https://example.org/synthetic", "title": "Synthetic source",
                 "content": "Synthetic public fact", "retrieved_at": 1}]

    monkeypatch.setattr("hub.api.execute_run", execute)
    monkeypatch.setattr("hub.websearch.search", search)
    provider.decision = Route(capabilities=["chat"], model_class="local", reason="Test")
    chat = client.post("/api/conversations", headers=headers,
                       json={"cloud_allowed": True}).json()["id"]
    response = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                           json={"content": PROMPT, "web_search_allowed": True})
    assert "succeeded" in response.text and provider.stream_calls == [True]
    detail = client.get(f"/api/conversations/{chat}").json()
    run = client.get("/api/runs/" + detail["runs"][0]["id"]).json()
    assert all(p["label"] == "CLOUD_ALLOWED" for p in run["context"]["parts"])
    assert run["routing"]["actual_provider"] == "openrouter"
