"""Versioned explicit integration stages at the actual private model boundary."""

import json
from uuid import uuid4

import pytest
from hub.db import Run
from hub.integrations import Integration
from hub.policy import ContextPart
from hub.use_cases import Definition, UseCase
from sqlalchemy import select
from test_use_case_ai import Model, ai_spec, run, wait

pytest_plugins = ["test_knowledge"]


def archive(app):
    with app.state.sessions() as db:
        row = Integration(
            name="Synthetic archive",
            kind="paperless",
            enabled=True,
            config=json.dumps({"url": "https://archive.example.test", "auth": "api_key"}),
            encrypted_secret="Synthetic stored credential",
            last_check=json.dumps({"revision": 1, "status": "succeeded"}),
        )
        db.add(row)
        db.commit()
        return row.id


@pytest.mark.parametrize("stage", ["integration_inputs", "integration_processing"])
def test_standalone_stage_reads_private_context(knowledge, monkeypatch, stage):
    app, client, headers, _, _ = knowledge
    identifier = archive(app)
    spec = ai_spec()
    spec[stage] = [identifier]
    case = client.post("/api/use-cases", headers=headers, json={"spec": spec}).json()
    assert case["spec"][stage] == [identifier]

    async def read(factory, cfg, selection, question):
        assert [item["id"] for item in selection["bindings"]] == [identifier]
        assert selection["stages"]["input" if stage.endswith("inputs") else "processing"] == [
            identifier
        ]
        return [ContextPart(content="PRIVATE synthetic OCR", source_id="paperless:7", revision=1)]

    monkeypatch.setattr("hub.paperless_api.collect_context", read)
    model = Model(["Synthetic analysis"])
    app.state.providers = model
    result = run(client, headers, case)
    finished = wait(client, f"/api/use-cases/{case['id']}/runs/{result['id']}")
    assert finished["status"] == "succeeded"
    assert any("PRIVATE synthetic OCR" in p.content for p in model.calls[0][0])
    assert model.calls[0][2] is False
    with app.state.sessions() as db:
        execution = db.scalar(select(Run))
        snapshot = json.loads(execution.context_snapshot)
        assert snapshot["integration_scope"] == {"scope": "use_case", "owner_id": case["id"]}
        assert snapshot["integration_selection"]["bindings"][0]["revision"] == 1
    rejected = client.post(
        f"/api/use-cases/{case['id']}/runs",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "values": {"goal": "Synthetic"},
            "model_mode": "cloud",
        },
    )
    assert rejected.status_code == 409


@pytest.mark.parametrize("change", ["disable", "revision", "definition"])
def test_stage_change_during_read_stops_model(knowledge, monkeypatch, change):
    app, client, headers, _, _ = knowledge
    identifier = archive(app)
    spec = ai_spec()
    spec["integration_inputs"] = [identifier]
    case = client.post("/api/use-cases", headers=headers, json={"spec": spec}).json()

    async def read(factory, cfg, selection, question):
        with factory() as db:
            row = (
                db.get(UseCase, case["id"])
                if change == "definition"
                else db.get(Integration, identifier)
            )
            if change == "disable":
                row.enabled = False
            else:
                row.revision += 1
            db.commit()
        return [ContextPart(content="PRIVATE OCR", source_id="paperless:7", revision=1)]

    monkeypatch.setattr("hub.paperless_api.collect_context", read)
    model = Model(["Should never reach model"])
    app.state.providers = model
    result = run(client, headers, case)
    finished = wait(client, f"/api/use-cases/{case['id']}/runs/{result['id']}")
    assert finished["status"] == "failed"
    assert model.calls == []


def test_save_rejects_unready_stage_and_normalizes_identifiers(knowledge):
    app, client, headers, _, _ = knowledge
    identifier = archive(app)
    spec = ai_spec()
    spec["integration_inputs"] = [identifier, identifier]
    assert client.post("/api/use-cases", headers=headers, json={"spec": spec}).status_code == 422
    spec["integration_inputs"] = [identifier]
    with app.state.sessions() as db:
        db.get(Integration, identifier).enabled = False
        db.commit()
    assert client.post("/api/use-cases", headers=headers, json={"spec": spec}).status_code == 409
    old = Definition.model_validate(ai_spec())
    assert old.integration_inputs == [] and old.output_integration_id is None


def test_dialogue_uses_explicit_private_input(knowledge, monkeypatch):
    app, client, headers, _, _ = knowledge
    identifier = archive(app)
    spec = ai_spec(presentation="dialogue")
    spec["integration_inputs"] = [identifier]
    case = client.post("/api/use-cases", headers=headers, json={"spec": spec}).json()

    async def read(factory, cfg, selection, question):
        return [ContextPart(content="PRIVATE dialogue source", source_id="paperless:7", revision=1)]

    monkeypatch.setattr("hub.paperless_api.collect_context", read)
    model = Model([json.dumps({"question": "Welches Ziel?", "values": {}, "ready": False})])
    app.state.providers = model
    response = client.post(
        f"/api/use-cases/{case['id']}/dialogues",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "values": {},
            "model_mode": "auto",
        },
    )
    assert response.status_code == 200, response.text
    dialogue = wait(client, f"/api/use-cases/{case['id']}/dialogues/{response.json()['id']}")
    assert dialogue["status"] == "succeeded"
    assert model.calls[0][2] is False
    assert any("PRIVATE dialogue source" in part.content for part in model.calls[0][0])
