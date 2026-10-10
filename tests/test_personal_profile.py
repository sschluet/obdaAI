import asyncio
import json

import pytest
from hub.db import PersonalProfile, Run
from hub.personal_profile import context_for_provider, digest, freeze_profile
from hub.policy import Privacy, check_egress
from hub.routing import Route
from sqlalchemy import select

pytest_plugins = ["test_chat"]


def save(client, headers, **overrides):
    body = client.get("/api/personal-profile").json()
    body.update(overrides)
    return client.put("/api/personal-profile", headers=headers, json=body)


def snapshot(**overrides):
    value = {
        "format": "personal-profile-1",
        "revision": 3,
        "enabled": True,
        "fields": {"name": "SYNTHETIC_NAME", "challenges": "SYNTHETIC_PRIVATE"},
        "cloud_fields": ["name"],
    }
    value.update(overrides)
    # Canonical filled defaults are required for a verified frozen snapshot.
    from hub.personal_profile import ProfileInput

    value = {
        "format": value["format"],
        **ProfileInput.model_validate(
            {k: v for k, v in value.items() if k != "format"}
        ).model_dump(),
    }
    return {**value, "sha256": digest(value)}


def test_api_optional_defaults_auth_cas_clear_validation(setup):
    _, client, headers, _ = setup
    original = client.get("/api/personal-profile").json()
    assert original["revision"] == 0 and not original["enabled"]
    assert original["cloud_fields"] == [] and all(v == "" for v in original["fields"].values())
    body = {
        **original,
        "enabled": True,
        "fields": {"name": "Synthetic User"},
        "cloud_fields": ["name"],
    }
    assert (
        client.put(
            "/api/personal-profile", json=body, headers={"Origin": "http://testserver"}
        ).status_code
        == 403
    )
    result = client.put("/api/personal-profile", json=body, headers=headers)
    assert result.status_code == 200 and result.json()["revision"] == 1
    assert client.put("/api/personal-profile", json=body, headers=headers).status_code == 409
    for extra in (
        {"cloud_fields": ["unknown"]},
        {"cloud_fields": ["name", "name"]},
        {"fields": {"name": "x" * 201}},
        {"fields": {"permissions": "cloud"}},
        {
            "fields": {
                k: "x" * 2000 for k in ["challenges", "goals", "interests", "additional_info"]
            }
            | {"name": "x"}
        },
    ):
        assert save(client, headers, **extra).status_code == 422
    cleared = save(client, headers, enabled=False, fields={}, cloud_fields=[])
    assert cleared.status_code == 200 and cleared.json()["revision"] == 2
    assert all(v == "" for v in cleared.json()["fields"].values())
    client.post("/api/logout", headers=headers)
    assert client.get("/api/personal-profile").status_code == 401


def test_provider_boundary_shares_only_explicit_subset_and_no_permission_grants():
    frozen = snapshot()
    parts, grants, audit = context_for_provider(frozen, external=True, provider_id="openrouter")
    assert len(parts) == 1 and parts[0].label == Privacy.CLOUD_ALLOWED
    assert "SYNTHETIC_NAME" in parts[0].content and "SYNTHETIC_PRIVATE" not in parts[0].content
    assert audit["applied_fields"] == ["name"] and audit["omitted_fields"] == ["challenges"]
    assert "SYNTHETIC" not in json.dumps(audit)
    check_egress(parts, external=True, provider_id="openrouter", grants=grants)
    with pytest.raises(PermissionError):
        check_egress(parts, external=True, provider_id="other", grants=grants)
    local, local_grants, _ = context_for_provider(frozen, external=False, provider_id="local")
    assert "SYNTHETIC_PRIVATE" in local[0].content and local[0].label == Privacy.LOCAL_ONLY
    assert local_grants == []
    with pytest.raises(PermissionError):
        check_egress(local, external=True, provider_id="openrouter", grants=grants)


@pytest.mark.parametrize("changes", [{"enabled": False}, {"cloud_fields": []}, {"fields": {}}])
def test_empty_disabled_or_unshared_does_not_inject_cloud(changes):
    parts, grants, audit = context_for_provider(
        snapshot(**changes), external=True, provider_id="openrouter"
    )
    assert parts == [] and grants == [] and audit["applied_fields"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": 4},
        {"sha256": "0" * 64},
        {"cloud_fields": ["challenges"]},
        {"format": "unknown"},
        {"permissions": "grant cloud"},
        {"fields": {"goals": 123}},
    ],
)
def test_corrupt_snapshot_fails_closed(changes):
    with pytest.raises(ValueError):
        context_for_provider({**snapshot(), **changes}, external=True, provider_id="openrouter")


@pytest.mark.parametrize("external,shared", [(False, False), (True, False), (True, True)])
def test_execution_profile_only_after_routing_frozen_and_labels(
    setup, monkeypatch, external, shared
):
    app, client, headers, provider = setup
    save(
        client,
        headers,
        enabled=True,
        fields={"name": "SYNTHETIC_NAME", "challenges": "SYNTHETIC_PRIVATE"},
        cloud_fields=["name"] if shared else [],
    )
    provider.decision = Route(
        capabilities=["chat"],
        model_class="cloud" if external else "local",
        reason="synthetic",
        answer=None if external else "short answer",
    )
    captured = []
    original_stream = provider.stream

    async def stream(parts, roles, **kwargs):
        captured.extend(parts)
        assert roles[-1] == "user"
        async for chunk in original_stream(parts, roles, **kwargs):
            yield chunk

    original_route = provider.route

    async def route(parts, roles):
        assert "SYNTHETIC_PRIVATE" not in json.dumps([p.content for p in parts])
        assert "SYNTHETIC_NAME" not in json.dumps([p.content for p in parts])
        return await original_route(parts, roles)

    async def noop(factory, settings, providers, run_id):
        with factory() as db:
            db.get(Run, run_id).status = "succeeded"
            db.commit()

    monkeypatch.setattr(provider, "route", route)
    monkeypatch.setattr(provider, "stream", stream)
    monkeypatch.setattr("hub.api.execute_run", noop)
    chat = client.post(
        "/api/conversations", headers=headers, json={"cloud_allowed": external}
    ).json()["id"]
    response = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "synthetic question", "web_search_allowed": False},
    )
    assert response.status_code == 200
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == chat))
        frozen = json.loads(run.context_snapshot)
        assert "SYNTHETIC_PRIVATE" not in json.dumps(frozen["parts"])
        assert frozen["personal_profile"]["revision"] == 1
        run_id = run.id
        assert freeze_profile(db) == frozen["personal_profile"]
        run.status = "queued"
        db.commit()
    save(client, headers, fields={"name": "MUTATED_NAME"})
    from hub.execution import execute_run

    asyncio.run(execute_run(app.state.sessions, app.state.settings, provider, run_id))
    detail = client.get(f"/api/conversations/{chat}").json()
    assert detail["runs"][-1]["status"] == "succeeded"
    assert "MUTATED_NAME" not in json.dumps([p.content for p in captured])
    data = json.dumps([p.content for p in captured])
    assert ("SYNTHETIC_NAME" in data) == (not external or shared)
    assert ("SYNTHETIC_PRIVATE" in data) == (not external)
    answer = detail["messages"][-1]
    assert answer["label"] == ("CLOUD_ALLOWED" if external else "LOCAL_ONLY")
    audit = client.get(f"/api/runs/{run_id}").json()["routing"]["personal_profile"]
    assert audit["revision"] == 1 and "SYNTHETIC" not in json.dumps(audit)
    assert detail["runs"][-1]["provider"] == ("openrouter" if external else "local")


def test_corrupt_storage_reported_and_can_be_replaced(setup):
    app, client, headers, _ = setup
    with app.state.sessions() as db:
        db.get(PersonalProfile, 1).fields = '{"name":123}'
        db.commit()
    assert client.get("/api/personal-profile").status_code == 409
    assert (
        client.put(
            "/api/personal-profile", headers=headers, json={"revision": 0, "fields": {}}
        ).status_code
        == 200
    )


def test_profile_not_in_public_search_or_title_request(setup, monkeypatch):
    from dataclasses import replace

    from hub.execution import execute_run

    app, client, headers, provider = setup
    save(
        client,
        headers,
        enabled=True,
        fields={"name": "SYNTHETIC_NAME", "challenges": "SYNTHETIC_PRIVATE"},
    )
    cfg = replace(app.state.settings, search_url="https://synthetic-search.invalid/search")
    captured = []

    async def execute(factory, settings, providers, run_id):
        await execute_run(factory, cfg, providers, run_id)

    async def search(settings, request, *, options):
        captured.append(request.model_dump())
        return [
            {
                "url": "https://example.org/synthetic",
                "title": "Synthetic source",
                "content": "Synthetic public fact",
                "retrieved_at": 1,
            }
        ]

    async def title(parts, roles):
        captured.extend(p.model_dump(mode="json") for p in parts)
        return "Synthetic title"

    monkeypatch.setattr("hub.api.execute_run", execute)
    monkeypatch.setattr("hub.websearch.search", search)
    monkeypatch.setattr(provider, "title", title)
    chat = client.post("/api/conversations", headers=headers, json={"cloud_allowed": True}).json()[
        "id"
    ]
    response = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "public synthetic research", "web_search_allowed": True},
    )
    assert "succeeded" in response.text
    assert captured and "SYNTHETIC_PRIVATE" not in json.dumps(captured)
    assert "SYNTHETIC_NAME" not in json.dumps(captured)
    # The saved answer came from the local profile context and remains protected.
    detail = client.get(f"/api/conversations/{chat}").json()
    assert detail["messages"][-1]["label"] == "LOCAL_ONLY"
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="next fixture")
    client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "next question", "web_search_allowed": False},
    )
    assert provider.stream_calls == [False, False]


def test_disabled_saved_facts_are_not_copied_into_new_run_history(setup):
    app, client, headers, _ = setup
    assert (
        save(
            client,
            headers,
            enabled=False,
            fields={"name": "SYNTHETIC_DISABLED_PRIVATE"},
            cloud_fields=["name"],
        ).status_code
        == 200
    )
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    response = client.post(
        "/api/conversations/" + chat + "/messages",
        headers=headers,
        json={"content": "Synthetic ordinary question"},
    )
    assert response.status_code == 200
    with app.state.sessions() as db:
        run = db.scalar(select(Run).where(Run.conversation_id == chat))
        frozen = json.loads(run.context_snapshot)["personal_profile"]
        assert not any(frozen["fields"].values()) and frozen["cloud_fields"] == []
        assert "SYNTHETIC_DISABLED_PRIVATE" not in run.context_snapshot
    assert (
        client.get("/api/personal-profile").json()["fields"]["name"] == "SYNTHETIC_DISABLED_PRIVATE"
    )
