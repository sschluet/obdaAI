"""Designer uses the normal durable model boundary; generated definitions remain drafts."""

import json
import time
from uuid import uuid4

import pytest
from hub.db import Conversation, Message, Run
from hub.policy import check_egress
from hub.use_case_designer import UseCaseDesigner, UseCaseDesignerTurn, proposal_output
from hub.use_cases import UseCase
from sqlalchemy import func, select

pytest_plugins = ["test_knowledge", "test_chat"]


def spec():
    return {
        "execution_kind": "ai",
        "name": "Synthetic invoice review",
        "processing_prompt": "Compare the provided invoices and explain discrepancies.",
        "presentation": "form",
        "fields": [{"key": "invoice", "label": "Invoice", "type": "file"}],
        "output_kind": "chat",
        "output_columns": [],
    }


class Model:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def stream(self, parts, roles, *, external, grants):
        check_egress(
            parts,
            external=external,
            provider_id="openrouter" if external else "local",
            grants=grants,
        )
        self.calls.append((parts, roles, external))
        yield self.responses.pop(0)

    async def route(self, parts, roles):
        pytest.fail("Designer must never dispatch actionable tool routing")

    async def title(self, *args):
        pytest.fail("Designer must remain hidden without ordinary chat titles")


def wait(client, identifier):
    for _ in range(200):
        response = client.get(f"/api/use-case-designer/dialogues/{identifier}")
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] not in {"queued", "routing", "streaming"}:
            return value
        time.sleep(0.01)
    pytest.fail("Designer did not finish")


def start(client, headers, request_id=None, **extra):
    response = client.post(
        "/api/use-case-designer/dialogues",
        headers=headers,
        json={
            "prompt": "Create an invoice comparison workflow",
            "request_id": request_id or str(uuid4()),
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_actual_model_clarification_then_editable_proposal_and_replay(knowledge):
    app, client, headers, _, _ = knowledge
    model = app.state.providers = Model(
        [
            json.dumps({"message": "Which input format?", "proposal": None}),
            json.dumps({"message": "Here is your draft", "proposal": spec()}),
        ]
    )
    request_id = str(uuid4())
    first = start(client, headers, request_id)
    done = wait(client, first["id"])
    assert done["status"] == "succeeded", done
    assert done["messages"][-1]["content"] == "Which input format?"
    assert done["proposal"] is None
    replay = start(client, headers, request_id)
    assert replay["id"] == first["id"] and len(model.calls) == 1
    body = {"content": "PDF files", "request_id": str(uuid4()), "expected_turn": 1}
    path = f"/api/use-case-designer/dialogues/{first['id']}/messages"
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 200, response.text
    done = wait(client, first["id"])
    assert done["proposal"]["processing_prompt"] == spec()["processing_prompt"]
    assert done["proposal"]["fields"][0]["type"] == "file"
    assert client.post(path, headers=headers, json=body).status_code == 200
    assert len(model.calls) == 2 and not any(call[2] for call in model.calls)
    assert "PDF files" in model.calls[1][0][-1].content
    assert model.calls[1][1] == ["system", "user", "assistant", "user"]
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(UseCase)) == 0
        assert db.scalar(select(Conversation)).purpose == "use_case_designer"
    assert client.get("/api/conversations").json() == []
    stale = {**body, "request_id": str(uuid4()), "expected_turn": 1}
    assert client.post(path, headers=headers, json=stale).status_code == 409
    assert (
        client.delete(
            f"/api/use-case-designer/dialogues/{first['id']}", headers=headers
        ).status_code
        == 200
    )
    with app.state.sessions() as db:
        for table in (UseCaseDesigner, UseCaseDesignerTurn, Conversation, Message, Run):
            assert db.scalar(select(func.count()).select_from(table)) == 0


def test_invalid_proposal_preserves_raw_text_and_allows_clarification(knowledge):
    app, client, headers, _, _ = knowledge
    app.state.providers = Model(["An unstructured answer"])
    item = start(client, headers)
    done = wait(client, item["id"])
    assert done["status"] == "succeeded"
    assert done["proposal"] is None and done["validation_error"]
    assert done["messages"][-1]["content"] == "An unstructured answer"


def test_auth_csrf_cloud_boundary_and_idempotency_conflict(knowledge):
    app, client, headers, _, _ = knowledge
    app.state.providers = Model([json.dumps({"message": "Which output?", "proposal": None})])
    payload = {"prompt": "Synthetic draft", "request_id": str(uuid4())}
    assert client.post("/api/use-case-designer/dialogues", json=payload).status_code == 403
    assert (
        client.post(
            "/api/use-case-designer/dialogues",
            headers=headers,
            json={**payload, "model_mode": "cloud"},
        ).status_code
        == 409
    )
    item = client.post("/api/use-case-designer/dialogues", headers=headers, json=payload).json()
    wait(client, item["id"])
    assert (
        client.post(
            "/api/use-case-designer/dialogues",
            headers=headers,
            json={**payload, "prompt": "Changed"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/use-case-designer/dialogues",
            headers=headers,
            json={**payload, "request_id": str(uuid4()), "prompt": " "},
        ).status_code
        == 422
    )


def test_proposal_cannot_select_remote_actions_and_requires_actual_ai_prompt():
    value = spec()
    value["integrations"] = {"output": [{"integration_id": str(uuid4()), "operation": "mail.send"}]}
    value["integration_inputs"] = [str(uuid4())]
    value["integration_processing"] = [str(uuid4())]
    value["output_integration_id"] = str(uuid4())
    _, proposal = proposal_output(json.dumps({"message": "Review draft", "proposal": value}))
    assert not proposal.get("integrations")
    assert proposal["integration_inputs"] == []
    assert proposal["integration_processing"] == []
    assert proposal["output_integration_id"] is None
    value = spec()
    value["processing_prompt"] = ""
    with pytest.raises(ValueError):
        proposal_output(json.dumps({"message": "Review", "proposal": value}))
    with pytest.raises(ValueError):
        proposal_output(json.dumps({"message": "Review", "proposal": spec(), "execute": True}))


def test_explicit_cloud_uses_only_entered_designer_context(setup):
    app, client, headers, _ = setup
    model = app.state.providers = Model(
        [json.dumps({"message": "Review draft", "proposal": spec()})]
    )
    item = start(client, headers, model_mode="cloud")
    done = wait(client, item["id"])
    assert done["status"] == "succeeded", done
    assert done["proposal"]["name"] == spec()["name"]
    parts, roles, external = model.calls[0]
    assert external and roles == ["system", "user"]
    assert all(p.label == "CLOUD_ALLOWED" for p in parts)
    with app.state.sessions() as db:
        execution = db.get(Run, done["execution_run_id"])
        frozen = json.loads(execution.context_snapshot)
        assert frozen["web_search_allowed"] is False
        assert "personal_profile" not in frozen and "integration_selection" not in frozen


def test_completed_designer_restores_on_app_restart(knowledge):
    from fastapi.testclient import TestClient
    from hub.api import create_app

    app, client, headers, cfg, _ = knowledge
    app.state.providers = Model([json.dumps({"message": "Review draft", "proposal": spec()})])
    item = start(client, headers)
    wait(client, item["id"])
    restored = create_app(cfg)
    restored.state.providers = Model([])
    with TestClient(restored) as other:
        login = other.post(
            "/api/login",
            headers={"Origin": cfg.origin},
            json={"password": "synthetic-knowledge-password"},
        )
        assert login.status_code == 200
        response = other.get(f"/api/use-case-designer/dialogues/{item['id']}")
        assert response.status_code == 200
        assert response.json()["proposal"]["name"] == spec()["name"]
        assert response.json()["status"] == "succeeded"
        assert restored.state.providers.calls == []
