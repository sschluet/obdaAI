import asyncio
import json

import pytest
from hub.db import PersonalProfile, Run
from hub.personal_profile import (
    ProfileFields,
    context_for_provider,
    digest,
    freeze_profile,
    relevant_profile_fields,
)
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
    parts, grants, audit = context_for_provider(
        frozen,
        external=True,
        provider_id="openrouter",
        question="Berücksichtige mein persönliches Profil",
    )
    assert len(parts) == 1 and parts[0].label == Privacy.CLOUD_ALLOWED
    assert "SYNTHETIC_NAME" in parts[0].content and "SYNTHETIC_PRIVATE" not in parts[0].content
    assert audit["applied_fields"] == ["name"] and audit["omitted_fields"] == ["challenges"]
    assert "SYNTHETIC" not in json.dumps(audit)
    check_egress(parts, external=True, provider_id="openrouter", grants=grants)
    with pytest.raises(PermissionError):
        check_egress(parts, external=True, provider_id="other", grants=grants)
    local, local_grants, _ = context_for_provider(
        frozen,
        external=False,
        provider_id="local",
        question="Berücksichtige mein persönliches Profil",
    )
    assert "SYNTHETIC_PRIVATE" in local[0].content and local[0].label == Privacy.LOCAL_ONLY
    assert local_grants == []
    with pytest.raises(PermissionError):
        check_egress(local, external=True, provider_id="openrouter", grants=grants)


@pytest.mark.parametrize("changes", [{"enabled": False}, {"cloud_fields": []}, {"fields": {}}])
def test_empty_disabled_or_unshared_does_not_inject_cloud(changes):
    parts, grants, audit = context_for_provider(
        snapshot(**changes),
        external=True,
        provider_id="openrouter",
        question="Berücksichtige mein persönliches Profil",
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
        context_for_provider(
            {**snapshot(), **changes},
            external=True,
            provider_id="openrouter",
            question="Berücksichtige mein persönliches Profil",
        )


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
        assert roles[0] == "system"
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
        json={"content": "Berücksichtige mein persönliches Profil", "web_search_allowed": False},
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
        json={
            "content": "Recherchiere öffentlich nach Strategien für meine Herausforderungen",
            "web_search_allowed": True,
        },
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


@pytest.mark.parametrize("local_only", [False, True])
def test_fully_shared_profile_derivatives_allow_auto_cloud_but_local_override_stays_private(
    setup, local_only
):
    app, client, headers, provider = setup
    assert (
        save(
            client,
            headers,
            enabled=True,
            fields={"name": "SYNTHETIC_SHARED"},
            cloud_fields=["name"],
        ).status_code
        == 200
    )
    chat = client.post("/api/conversations", headers=headers, json={"cloud_allowed": True}).json()[
        "id"
    ]
    response = client.post(
        "/api/conversations/" + chat + "/messages",
        headers=headers,
        json={"content": "Wie ist mein Name?", "local_only": local_only},
    )
    assert response.status_code == 200
    detail = client.get("/api/conversations/" + chat).json()
    assert detail["messages"][-1]["label"] == ("LOCAL_ONLY" if local_only else "CLOUD_ALLOWED")
    provider.decision = Route(capabilities=["chat"], model_class="cloud", reason="complex fixture")
    response = client.post(
        "/api/conversations/" + chat + "/messages",
        headers=headers,
        json={"content": "Synthetic next question", "cloud_allowed": True},
    )
    assert response.status_code == 200
    assert provider.stream_calls == [False, not local_only]


@pytest.mark.parametrize(
    "question",
    [
        None,
        "",
        "   ",
        "Hallo",
        "Zeige mir meine Home Assistant Geräte",
        "Bitte rufe alle Geräte in Home Assistant auf",
        (
            "Erstelle eine komplexe Recherche zum Thema Managed Services in der Zukunft "
            "vor dem Hintergrund AI und den aktuellen Entwicklungen"
        ),
        "Erstelle für mich eine Recherche zur Zukunft von Managed Services",
        "Was bedeutet die Rolle COO in einem Unternehmen?",
        "Empfiehl IT-Geräte für mich",
        "Wie behebe ich meine Probleme mit Home Assistant?",
        "Verwende keine persönlichen Informationen für meine Karriereplanung",
        "Erkläre Familienstand im Steuerrecht",
        "Berücksichtige mein persönliches Profil, aber bitte ohne persönliche Informationen",
        "Nutze mein Profil nicht verwenden",
        "Berücksichtige mein persönliches Profil nicht",
        "Verwende nicht mein Profil für meine Karriere",
        "Berate mich zu meiner Karriere, aber ohne Profil",
        "Consider my personal profile but do not personalize",
    ],
)
@pytest.mark.parametrize("external", [False, True])
def test_neutral_or_excluded_questions_never_receive_profile(question, external):
    fields = {key: "SYNTHETIC_" + key.upper() for key in ProfileFields.model_fields}
    parts, grants, audit = context_for_provider(
        snapshot(fields=fields, cloud_fields=list(fields)),
        external=external,
        provider_id="openrouter" if external else "local",
        question=question,
    )
    assert parts == grants == []
    assert audit["applied_fields"] == []
    assert set(audit["omitted_fields"]) == set(fields)
    assert "SYNTHETIC" not in json.dumps(audit)


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Wie heiße ich?", {"name", "preferred_name"}),
        ("Was ist mein Beruf?", {"profession"}),
        ("Welche Rolle ist meine Rolle?", {"profession"}),
        (
            "Wie kann ich Arbeit und Familie besser vereinbaren?",
            {"profession", "family_status", "goals", "challenges"},
        ),
        ("Wie sollst du mich ansprechen?", {"name", "preferred_name"}),
        ("What is my name?", {"name", "preferred_name"}),
        ("Berate mich zu meiner Karriere", {"profession", "goals", "challenges"}),
        ("Wie kann ich mich beruflich weiterentwickeln?", {"profession", "goals", "challenges"}),
        ("Welche Optionen passen zu meiner Familie?", {"family_status"}),
        ("Was sind meine Ziele?", {"goals"}),
        ("Wie gehe ich mit meinen Herausforderungen um?", {"challenges"}),
        ("Empfiehl etwas für meine Interessen", {"interests"}),
        ("Berücksichtige mein persönliches Profil", set(ProfileFields.model_fields)),
    ],
)
def test_personal_intent_selects_only_relevant_fields(question, expected):
    fields = {key: "SYNTHETIC_" + key.upper() for key in ProfileFields.model_fields}
    assert relevant_profile_fields(question) == expected
    parts, _, audit = context_for_provider(
        snapshot(fields=fields, cloud_fields=list(fields)),
        external=False,
        provider_id="local",
        question=question,
    )
    assert set(audit["applied_fields"]) == expected
    data = json.loads(parts[0].content.split("\n", 1)[1])
    assert set(data) == expected


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize(
    "question,expected",
    [
        ("Zeige mir meine Home Assistant Geräte", set()),
        ("Recherchiere die Zukunft von Managed Services", set()),
        ("Berate mich zu meiner Karriere", {"profession", "goals", "challenges"}),
    ],
)
def test_execution_relevance_applies_before_local_or_cloud_provider(
    setup, monkeypatch, external, question, expected
):
    _, client, headers, provider = setup
    fields = {key: "SYNTHETIC_" + key.upper() for key in ProfileFields.model_fields}
    save(client, headers, enabled=True, fields=fields, cloud_fields=list(fields)).raise_for_status()
    provider.decision = Route(
        capabilities=["chat"], model_class="cloud" if external else "local", reason="synthetic"
    )
    seen = []
    original = provider.stream

    async def stream(parts, roles, **kwargs):
        seen.extend(zip(parts, roles, strict=True))
        async for chunk in original(parts, roles, **kwargs):
            yield chunk

    monkeypatch.setattr(provider, "stream", stream)
    chat = client.post(
        "/api/conversations", headers=headers, json={"cloud_allowed": external}
    ).json()["id"]
    result = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": question, "web_search_allowed": False},
    )
    assert "succeeded" in result.text
    applied = {
        key for key, value in fields.items() if value in " ".join(p.content for p, _ in seen)
    }
    assert applied == expected
    assert any(
        p.source_id == "personal-relevance-policy-1" and role == "system" for p, role in seen
    )
    assert provider.stream_calls == [external]
    run = client.get(f"/api/conversations/{chat}").json()["runs"][-1]
    audit = client.get(f"/api/runs/{run['id']}").json()["routing"]["personal_profile"]
    assert set(audit["applied_fields"]) == expected


@pytest.mark.parametrize("external", [False, True])
def test_new_neutral_question_does_not_reapply_profile_from_personal_history(
    setup, monkeypatch, external
):
    from hub.db import Message

    app, client, headers, provider = setup
    save(
        client,
        headers,
        enabled=True,
        fields={"profession": "SYNTHETIC_COO", "goals": "SYNTHETIC_CAREER"},
        cloud_fields=["profession", "goals"],
    ).raise_for_status()
    provider.decision = Route(
        capabilities=["chat"], model_class="cloud" if external else "local", reason="synthetic"
    )
    chat = client.post(
        "/api/conversations", headers=headers, json={"cloud_allowed": external}
    ).json()["id"]
    client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Berate mich zu meiner Karriere", "web_search_allowed": False},
    )
    with app.state.sessions() as db:
        previous = db.scalar(
            select(Message).where(Message.conversation_id == chat, Message.role == "assistant")
        )
        previous.content = "Synthetic prior career advice as COO: focus on family and finances."
        previous_label = previous.label
        db.commit()
    captured = []
    original = provider.stream

    async def stream(parts, roles, **kwargs):
        captured.extend(parts)
        async for chunk in original(parts, roles, **kwargs):
            yield chunk

    monkeypatch.setattr(provider, "stream", stream)
    response = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={
            "content": "Recherchiere die Zukunft von Managed Services",
            "web_search_allowed": False,
        },
    )
    assert "succeeded" in response.text
    assert not any(p.source_id.startswith("personal-profile:") for p in captured)
    assert any(p.source_id == "personal-relevance-policy-1" for p in captured)
    assert any(
        "Synthetic prior career advice" in p.content and p.label.value == previous_label
        for p in captured
    )
    run = client.get(f"/api/conversations/{chat}").json()["runs"][-1]
    assert (
        client.get(f"/api/runs/{run['id']}").json()["routing"]["personal_profile"]["applied_fields"]
        == []
    )


def test_relevance_guard_respects_local_only_provider_labels(setup, monkeypatch):
    from dataclasses import replace

    app, client, headers, provider = setup
    from hub.execution import execute_run

    async def local_execute(factory, settings, providers, run_id):
        await execute_run(
            factory, replace(settings, local_allowed_labels=("LOCAL_ONLY",)), providers, run_id
        )

    monkeypatch.setattr("hub.api.execute_run", local_execute)
    provider.decision = Route(capabilities=["chat"], model_class="local", reason="synthetic")
    original = provider.stream
    captured = []

    async def stream(parts, roles, **kwargs):
        assert all(part.label == Privacy.LOCAL_ONLY for part in parts)
        captured.extend(parts)
        async for chunk in original(parts, roles, **kwargs):
            yield chunk

    monkeypatch.setattr(provider, "stream", stream)
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    response = client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "Erkläre Managed Services", "web_search_allowed": False},
    )
    assert "succeeded" in response.text
    assert any(p.source_id == "personal-relevance-policy-1" for p in captured)
