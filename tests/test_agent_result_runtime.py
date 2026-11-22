"""Shared dispatch must reject unsuccessful data selection and fixed inspection."""

import json

import pytest
from hub import agent_runtime as runtime
from hub.agent_models import AgentJob, AgentPolicy
from hub.agent_tools import Rules
from hub.integrations import Integration
from hub.provider_settings import encrypt
from test_actions import gateway, set_pause  # noqa: F401
from test_agent_capability_runtime import execute, ha, no_planning, start  # noqa: F401
from test_agents import agent  # noqa: F401
from test_integration_writes import writes  # noqa: F401


@pytest.mark.parametrize("missing_first", [False, True])
def test_failed_projection_cannot_prove_an_answer_or_resolve_a_missing_endpoint(
    ha, monkeypatch, missing_first  # noqa: F811
):
    sent, turns = [], []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        sent.append(args["path"])
        if args["path"] == "/api/":
            return {"http_status": 200, "body": {"message": "API running."}}
        if args["path"] == "/api/light":
            return {"http_status": 404, "body": {}}
        return {"http_status": 200, "body": {"unfiltered": "private data"},
                "projection_error": "SYNTHETIC-PRIVATE-TARGET-ERROR"}

    async def model(*args):
        turns.append(args[-1])
        path = "/api/light" if missing_first and len(turns) == 1 else "/api/states"
        return {"kind": "tool", "integration_id": ha[4], "tool": "http",
                "message": "Read inventory", "arguments": {"method": "GET", "path": path}}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha, "Welche Lampen habe ich in Home Assistant?"))
    assert result["status"] == "failed" and "Lesezugriff fehlgeschlagen" in result["summary"]
    assert "SYNTHETIC-PRIVATE-TARGET-ERROR" not in result["summary"]
    assert len(turns) == (2 if missing_first else 1)
    assert sent == (["/api/", "/api/light", "/api/states"]
                    if missing_first else ["/api/", "/api/states"])
    failed = [s for s in result["steps"] if s["status"] == "failed"]
    assert failed[-1]["result"]["failure_category"] == "validation_error"
    assert not any(s["kind"] == "effect" for s in result["steps"])


@pytest.mark.parametrize("exit_code", [1, 127, None, True])
def test_ssh_access_cannot_succeed_after_unsuccessful_fixed_inspection(
    ha, monkeypatch, exit_code  # noqa: F811
):
    no_planning(monkeypatch)
    app, _, _, _, identifier, *_ = ha
    with app.state.sessions() as db:
        profile = db.get(Integration, identifier)
        profile.kind, profile.name = "ssh", "Mac mini"
        profile.config = json.dumps({"kind": "ssh", "url": "host.example.test"})
        db.commit()
    sent = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        sent.append(tool)
        return {"exit_code": exit_code, "stdout": "Misleading partial output", "stderr": ""}

    monkeypatch.setattr(runtime, "invoke", invoke)
    result = execute(ha, start(ha, "Kannst du auf Mac mini zugreifen?"))
    assert sent == ["ssh.inspect"] and result["status"] == "failed"
    assert result["steps"][0]["result"]["failure_category"] == "remote_tool_error"


def test_mixed_access_validates_each_ha_response_independently(ha, monkeypatch):  # noqa: F811
    no_planning(monkeypatch)
    app, client, headers, cfg, identifier, chat, *_ = ha
    with app.state.sessions() as db:
        ssh = Integration(name="Mac mini", kind="ssh", enabled=True,
                          config=json.dumps({"kind": "ssh", "url": "host.example.test"}))
        db.add(ssh)
        db.flush()
        ssh_id = ssh.id
        ssh.encrypted_secret = encrypt(cfg, "integration:" + ssh_id, "synthetic-write-token")
        db.add(AgentPolicy(integration_id=ssh_id, profile_revision=ssh.revision,
                           rules=Rules(enabled=True, max_effects=0).model_dump_json()))
        db.commit()
    response = client.put(
        f"/api/integration-bindings/conversation/{chat}",
        json={"expected_revision": 1, "selection_mode": "manual",
              "integration_ids": [identifier, ssh_id]}, headers=headers,
    )
    assert response.status_code == 200, response.text
    sent = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        sent.append(tool)
        if tool == "http":
            return {"http_status": 200, "body": {"message": "Another application"}}
        return {"exit_code": 0, "stdout": "Linux\nuser\nup\nOBDAAI_COMMAND_AVAILABILITY\n",
                "stderr": ""}

    monkeypatch.setattr(runtime, "invoke", invoke)
    result = execute(ha, start(ha))
    assert sorted(sent) == ["http", "ssh.inspect"]
    assert result["status"] == "failed" and "nicht bestätigt" in result["summary"]


def test_inventory_default_binds_no_effects_and_rejects_model_confirmation(ha, monkeypatch):  # noqa: F811
    sent = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        sent.append(tool)
        return {"http_status": 200, "body": {"message": "API running."}}

    async def model(*args):
        data = args[-1]
        assert data["read_only"] is True and data["allow_ask"] is False
        return {"kind": "ask", "message": "Bitte bestätige den Lesezugriff."}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    job_id = start(ha, "Welche Lampen habe ich in Home Assistant?")
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        assert json.loads(job.bindings)["read_only"] is True and job.max_effects == 0
    result = execute(ha, job_id)
    assert result["status"] == "failed" and sent == ["http"]
    assert not any(s["kind"] in {"input", "effect"} for s in result["steps"])


def test_get_webhook_cannot_escape_an_inventory_read_boundary(ha, monkeypatch):  # noqa: F811
    sent = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        sent.append(args["path"])
        assert args["path"] == "/api/", "A webhook must never reach the transport"
        return {"http_status": 200, "body": {"message": "API running."}}

    async def model(*args):
        return {"kind": "tool", "message": "Unsafe alleged check", "integration_id": ha[4],
                "tool": "http", "arguments": {"method": "GET", "path": "/api/webhook/fake"}}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", model)
    result = execute(ha, start(ha, "Welche Lampen sind in Home Assistant vorhanden?"))
    assert result["status"] == "failed" and sent == ["/api/"]


def test_old_read_intent_with_changed_effect_classification_is_never_dispatched(
    ha, monkeypatch  # noqa: F811
):
    sent = []
    monkeypatch.setattr(runtime, "invoke", lambda *args: sent.append("forbidden"))
    job_id = start(ha, "Prüfe Home Assistant für die Wartung.")
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        step = runtime.record(db, job, "read", {
            "kind": "tool", "integration_id": ha[4], "tool": "http",
            "arguments": {"method": "GET", "path": "/api/webhook/fake"},
        })
        sequence = step.sequence
        db.commit()
    with pytest.raises(PermissionError, match="klassifikation"):
        runtime.dispatch(ha[0].state.sessions, ha[3], job_id, sequence)
    assert not sent
