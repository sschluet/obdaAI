"""Explicit Cloud is a provider choice, never a relaxation of context privacy."""
import json
import uuid

import pytest
from hub.db import BudgetReservation, ProviderConfig, Run
from hub.routing import Route
from hub.routing_settings import decision
from sqlalchemy import select
from test_chat import new_chat
from test_personal_profile import save
from test_skills import document

pytest_plugins = ["test_chat"]

CLOUD = {"cloud_allowed": True, "model_cloud_only": True}


def test_cloud_simple_send_retry_edit_discard_local_inline_answer(setup):
    app, client, headers, provider = setup
    chat = new_chat(client, headers)
    response = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                           json={"content": "Hallo", **CLOUD})
    assert "succeeded" in response.text
    assert "SYNTHETIC_" in response.text and "STREAM" in response.text
    assert "SYNTHETIC_ANSWER" not in response.text
    detail = client.get(f"/api/conversations/{chat}").json()
    user = next(m for m in detail["messages"] if m["role"] == "user")
    result = client.post(f"/api/conversations/{chat}/retry", headers=headers,
                         json={"request_id": str(uuid.uuid4()), **CLOUD})
    assert "succeeded" in result.text
    result = client.patch(f"/api/conversations/{chat}/messages/{user['id']}", headers=headers,
                          json={"content": "Hi", "revision": user["revision"], **CLOUD})
    assert "succeeded" in result.text and provider.stream_calls == [True, True, True]
    with app.state.sessions() as db:
        runs = list(db.scalars(select(Run).where(Run.conversation_id == chat)))
        assert len(runs) == 3
        for run in runs:
            assert json.loads(run.context_snapshot)["model_cloud_only"] is True
            trace = json.loads(run.routing_trace)
            assert trace["requested_mode"] == "cloud"
            assert trace["effective_model_class"] == "cloud"
            assert run.provider == "openrouter" and run.answer_model_used


@pytest.mark.parametrize("extra", [{"local_only": True}, {"model_local_only": True},
                                  {"cloud_allowed": False}])
def test_cloud_conflicting_flags_rejected_before_enqueue(setup, extra):
    app, client, headers, provider = setup
    chat = new_chat(client, headers)
    response = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                           json={"content": "Hallo", **CLOUD, **extra})
    assert response.status_code == 422 and provider.calls == 0
    with app.state.sessions() as db:
        assert db.scalar(select(Run)) is None


def test_cloud_preserves_old_private_history_but_retry_can_share_current_question(setup):
    _, client, headers, provider = setup
    chat = new_chat(client, headers)
    client.post(f"/api/conversations/{chat}/messages", headers=headers, json={"content": "Private"})
    response = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                           json={"content": "Hallo", **CLOUD})
    assert response.status_code == 409 and "geschützte Historie" in response.text
    assert provider.stream_calls == []
    old = client.get(f"/api/conversations/{chat}").json()["messages"]
    assert all(m["label"] == "LOCAL_ONLY" for m in old)
    response = client.post(f"/api/conversations/{chat}/retry", headers=headers,
                           json={"request_id": str(uuid.uuid4()), **CLOUD})
    assert "succeeded" in response.text and provider.stream_calls == [True]


@pytest.mark.parametrize("kind", ["project", "knowledge"])
def test_cloud_cannot_promote_private_scopes(setup, kind):
    _, client, headers, provider = setup
    if kind == "project":
        project = client.post("/api/projects", headers=headers,
                              json={"name": "Synthetic private project"}).json()
        body = {"project_id": project["id"]}
    else:
        body = {"memory_scope": "global"}
    response = client.post("/api/conversations", headers=headers, json=body)
    assert response.status_code == 200, response.text
    chat = response.json()["id"]
    result = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                         json={"content": "Hallo", **CLOUD})
    assert result.status_code == 409 and "LOCAL_ONLY" in result.text
    assert provider.calls == 0 and provider.stream_calls == []


def test_cloud_unshared_skill_blocks_and_profile_only_shares_reviewed_subset(setup, monkeypatch):
    _, client, headers, provider = setup
    skill = client.post("/api/skills", headers=headers,
                        json={"document": document(usage="always"), "activate": True})
    assert skill.status_code == 200
    chat = new_chat(client, headers)
    response = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                           json={"content": "Hallo", **CLOUD})
    assert response.status_code == 409 and provider.calls == 0
    client.patch(f"/api/conversations/{chat}/skills", headers=headers,
                 json={"skill_ids": [], "expected_selection": None}).raise_for_status()
    save(client, headers, enabled=True, fields={"name": "SYNTHETIC_SHARED",
                                              "challenges": "SYNTHETIC_PRIVATE"},
         cloud_fields=["name"]).raise_for_status()
    original = provider.stream
    seen = []

    async def stream(parts, roles, **kwargs):
        seen.extend(p.content for p in parts)
        async for chunk in original(parts, roles, **kwargs):
            yield chunk

    monkeypatch.setattr(provider, "stream", stream)
    response = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                           json={"content": "Hallo", **CLOUD})
    assert "succeeded" in response.text and provider.stream_calls == [True]
    assert "SYNTHETIC_SHARED" in " ".join(seen)
    assert "SYNTHETIC_PRIVATE" not in " ".join(seen)


def test_cloud_needs_no_local_classifier_or_model_tools(setup):
    _, client, headers, provider = setup
    provider.fail = True  # Local inference would fail if called.
    provider.decision = Route(
        capabilities=["chat", "tool"], model_class="local", reason="Synthetic"
    )
    chat = new_chat(client, headers)
    response = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                           json={"content": "Erläutere diese Systemwerkzeuge", **CLOUD})
    assert "succeeded" in response.text and provider.calls == 0
    assert provider.stream_calls == [True]
    assert "Systemprüfung gespeichert" not in response.text



def test_cloud_preview_no_complexity_required_and_private_is_blocked(setup):
    _, client, headers, provider = setup
    result = client.post("/api/routing-settings/preview", headers=headers,
                         json={"prompt": "Hi", "model_cloud_only": True}).json()
    assert result["effective_model_class"] == "cloud" and result["complexity"] == "simple"
    result = client.post("/api/routing-settings/preview", headers=headers,
                         json={"prompt": "Hi", "model_cloud_only": True,
                               "private_context": True}).json()
    assert result["effective_model_class"] == "blocked" and result["blockers"]
    assert provider.calls == 0
    # Even an inline classifier result is discarded; strategy cannot undo explicit Cloud.
    trace = decision("Hi", {"strategy": "local_first"}, classifier="local", cloud_enabled=True,
                     cloud_allowed=True, model_local_only=False, model_cloud_only=True,
                     private_context=False, builtin=True)
    assert trace["effective_model_class"] == "cloud"


@pytest.mark.parametrize("state", ["disabled", "missing_default", "budget", "allowed"])
def test_cloud_uses_configured_provider_and_budget_before_dispatch(setup, monkeypatch, state):
    import time

    from hub.policy import check_egress
    from hub.provider_settings import seed
    from hub.providers import Providers

    app, client, headers, _ = setup
    with app.state.sessions() as db:
        seed(db, app.state.settings)
        # Broken/disabled local inference cannot block an explicitly Cloud answer.
        local = db.get(ProviderConfig, "local-default")
        local.enabled = False
        local.config = "not valid local config"
        row = db.get(ProviderConfig, "openrouter-default")
        row.enabled = state != "disabled"
        row.is_default = state != "missing_default"
        data = json.loads(row.config)
        data.update(model="SYNTHETIC_CONFIGURED_CLOUD",
                    monthly_budget=0 if state == "budget" else 1,
                    max_run_cost=1, output_tokens=128,
                    pricing={"input": "0.000001", "output": "0.000001",
                             "verified_at": time.time()})
        row.config = json.dumps(data)
        db.commit()
    dispatched = []

    async def route(self, parts, roles):
        return Route(capabilities=["chat"], model_class="local", reason="Simple local route",
                     answer="DO_NOT_USE_LOCAL_INLINE")

    async def title(self, parts, roles):
        return "Synthetic cloud conversation"

    async def prices(factory, row, provider):
        return row

    async def stream(self, parts, roles, *, external, grants):
        check_egress(parts, external=external, provider_id=self.external_kind, grants=grants)
        dispatched.append((external, self.settings.openrouter_model))
        yield "SYNTHETIC_PROVIDER_RESPONSE"

    monkeypatch.setattr(Providers, "route", route)
    monkeypatch.setattr(Providers, "title", title)
    monkeypatch.setattr(Providers, "stream", stream)
    monkeypatch.setattr("hub.execution.fresh_cloud_prices", prices)
    app.state.providers = Providers(app.state.settings)
    chat = new_chat(client, headers)
    result = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                         json={"content": "Hi", **CLOUD})
    detail = client.get(f"/api/conversations/{chat}").json()
    run = detail["runs"][0]
    if state == "allowed":
        assert "succeeded" in result.text and dispatched == [(True, "SYNTHETIC_CONFIGURED_CLOUD")]
        assert run["provider"] == "openrouter"
        assert run["model"] == "SYNTHETIC_CONFIGURED_CLOUD"
        with app.state.sessions() as db:
            assert db.get(BudgetReservation, run["id"]) is not None
    else:
        assert "failed" in result.text and dispatched == []
        expected = "deaktiviert" if state in ("disabled", "missing_default") else "Monatsbudget"
        assert expected in result.text
        assert "DO_NOT_USE_LOCAL_INLINE" not in result.text
        assert all(m["role"] == "user" for m in detail["messages"])


def test_request_identity_binds_mode_and_cloud_public_research_needs_no_local_model(
    setup, monkeypatch
):
    from dataclasses import replace

    from hub.execution import execute_run

    app, client, headers, provider = setup
    provider.fail = True
    cfg = replace(app.state.settings, search_url="https://synthetic-search.invalid/search")
    queries = []

    async def execute(factory, settings, providers, run_id):
        await execute_run(factory, cfg, providers, run_id)

    async def search(settings, request, *, options):
        queries.append(request.query)
        return [{"url": "https://example.org/synthetic", "title": "Synthetic public source",
                 "content": "Synthetic public fact", "retrieved_at": 1}]

    monkeypatch.setattr("hub.api.execute_run", execute)
    monkeypatch.setattr("hub.websearch.search", search)
    chat = new_chat(client, headers)
    request_id = str(uuid.uuid4())
    body = {"content": "Recherchiere aktuelle Managed Services", "request_id": request_id,
            "web_search_allowed": True, **CLOUD}
    response = client.post(f"/api/conversations/{chat}/messages", headers=headers, json=body)
    assert "succeeded" in response.text and provider.calls == 0
    assert provider.stream_calls == [True] and queries == [body["content"]]
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.request_key == request_id))
        snap = json.loads(run.context_snapshot)
        assert all(p["label"] == "CLOUD_ALLOWED" for p in snap["parts"])
    replay = client.post(f"/api/conversations/{chat}/messages", headers=headers, json=body)
    assert replay.status_code == 200 and provider.stream_calls == [True]
    changed = client.post(f"/api/conversations/{chat}/messages", headers=headers,
                          json={**body, "model_cloud_only": False})
    assert changed.status_code == 409
