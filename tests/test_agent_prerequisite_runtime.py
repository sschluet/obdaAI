"""API/worker prerequisite gates include human approvals and final transport waits."""

import asyncio
import json

import pytest
from hub import agent_reconcile
from hub import agent_runtime as runtime
from hub.agent_intent import RequestIntent, Requirement
from hub.agent_models import AgentJob, AgentPolicy
from hub.agent_tools import Rules
from test_agent_capability_runtime import start
from test_agent_effect_prerequisites import RULE

pytest_plugins = ["test_agent_capability_runtime"]
GOAL = "Bitte prüfe Home Assistant und spiele alle ausstehenden Update ein"


def configure(ha, *, autonomous=True, rule=RULE):
    with ha[0].state.sessions() as db:
        policy = db.get(AgentPolicy, ha[4])
        revision = policy.revision
        rules = Rules.model_validate(
            {
                **json.loads(policy.rules),
                "effect_prerequisites": [rule],
                "autonomous": autonomous,
            }
        )
    response = ha[1].put(
        f"/api/integrations/{ha[4]}/agent-policy",
        headers=ha[2],
        json={
            "expected_revision": revision,
            "expected_profile_revision": 1,
            "rules": rules.model_dump(mode="json"),
        },
    )
    assert response.status_code == 200, response.text


def decision(identifier, path, *, method="GET", body=None, verification=None):
    return {
        "kind": "tool",
        "integration_id": identifier,
        "tool": "http",
        "message": "Synthetic operation",
        "arguments": {
            "method": method,
            "path": path,
            **({"body": body} if body is not None else {}),
            **({"verification": verification} if verification else {}),
        },
    }


def test_closed_all_update_pipeline_rejects_premature_change_then_backup_verify_update(
    ha, monkeypatch
):
    configure(ha)
    job_id = start(ha, GOAL, research_allowed=False)
    backup = {
        "path": "/api/states/sensor.backup",
        "expected": {"/body/state": "ready"},
        "timeout_seconds": 1,
        "interval_seconds": 1,
    }
    update = {
        "path": "/api/states/update.synthetic",
        "expected": {"/body/state": "off", "/body/attributes/installed_version": "2"},
        "timeout_seconds": 1,
        "interval_seconds": 1,
    }
    choices = iter(
        [
            decision(ha[4], "/api/states"),
            decision(
                ha[4],
                RULE["operation"]["path"],
                method="POST",
                body={"entity_id": "update.synthetic"},
                verification=update,
            ),
            decision(
                ha[4],
                RULE["requires"]["path"],
                method="POST",
                body={"name": "Synthetic"},
                verification=backup,
            ),
            decision(ha[4], "/api/states"),
            decision(
                ha[4],
                RULE["operation"]["path"],
                method="POST",
                body={"entity_id": "update.synthetic"},
                verification=update,
            ),
            decision(ha[4], "/api/states"),
            {"kind": "finish", "message": "All remotely installed"},
        ]
    )
    calls, seen = [], []
    state = {"backup": False, "installed": False}

    async def generate(*args):
        data = args[-1]
        if data.get("intent_schema"):
            return RequestIntent(
                mode="admin",
                topic="system",
                target_ids=[ha[4]],
                requirements=[
                    Requirement(kind="effect_postcondition", integration_id=ha[4]),
                    Requirement(kind="entity_states", integration_id=ha[4], domain="update"),
                ],
            ).model_dump()
        seen.append(data["execution_state"]["operation_prerequisites"])
        return next(choices)

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        calls.append((tool, args.get("method"), args["path"]))
        row = {
            "entity_id": "update.synthetic",
            "state": "off" if state["installed"] else "on",
            "attributes": {
                "installed_version": "2" if state["installed"] else "1",
                "latest_version": "2",
                "friendly_name": "Synthetic update",
            },
        }
        if tool == "http.verify":
            return {
                "http_status": 200,
                "verification_passed": state["backup"]
                if args["path"].endswith("sensor.backup")
                else state["installed"],
            }
        if args["method"] == "POST":
            if args["path"] == RULE["requires"]["path"]:
                state["backup"] = True
            else:
                assert state["backup"]
                state["installed"] = True
            return {"http_status": 200, "body": {}, "effect_verified": False}
        from hub.agent_context import project

        body = project([row], args["projection"]) if args.get("projection") else [row]
        return {
            "http_status": 200,
            "body": {"message": "API running."} if args["path"] == "/api/" else body,
        }

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(agent_reconcile, "invoke", invoke)
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, job_id))
    result = ha[1].get("/api/agent-runs/" + job_id).json()
    assert result["status"] == "succeeded", result["summary"]
    writes = [path for _, method, path in calls if method == "POST"]
    assert writes == [RULE["requires"]["path"], RULE["operation"]["path"]]
    assert any(not row[0]["satisfied"] for row in seen) and any(row[0]["satisfied"] for row in seen)
    feedback = [step for step in result["steps"] if step["kind"] == "feedback"]
    assert any(
        item["type"] == "effect_prerequisite_required"
        for step in feedback
        for item in step["document"]["issues"]
    )
    assert all(
        step["result"]["effect_verified"] is True
        for step in result["steps"]
        if step["kind"] == "effect"
    )


def seed_verified_backup(ha, job_id):
    with ha[0].state.sessions() as db:
        job = db.get(AgentJob, job_id)
        intent = RequestIntent(
            mode="admin",
            topic="general",
            target_ids=[ha[4]],
            requirements=[
                Requirement(kind="effect_postcondition", integration_id=ha[4]),
            ],
        )
        job.bindings = json.dumps(
            {**json.loads(job.bindings), "intent": intent.model_dump(mode="json")}
        )
        effect = runtime.record(
            db, job, "effect", decision(ha[4], RULE["requires"]["path"], method="POST")
        )
        effect.status = "succeeded"
        proof = runtime.record(
            db,
            job,
            "read",
            {
                "integration_id": ha[4],
                "tool": "http.verify",
                "arguments": {
                    "effect_step": effect.sequence,
                    "path": "/api/states/sensor.backup",
                    "expected": {"/body/state": "ready"},
                },
            },
        )
        proof.status, proof.result = "succeeded", json.dumps({"verification_passed": True})
        effect.result = json.dumps({"effect_verified": True, "verification_step": proof.sequence})
        db.commit()
        return proof.sequence


@pytest.mark.parametrize("stage", ["transport", "approval"])
def test_prerequisite_proof_revocation_cannot_be_bypassed_by_transport_or_human_approval(
    ha, monkeypatch, stage
):
    configure(ha, autonomous=stage != "approval")
    job_id = start(ha, "Change the synthetic remote state", research_allowed=False)
    proof_sequence = seed_verified_backup(ha, job_id)
    sent = []

    async def generate(*args):
        return decision(ha[4], RULE["operation"]["path"], method="POST")

    def revoke():
        with ha[0].state.sessions() as db:
            from hub.agent_models import AgentStep

            db.get(AgentStep, (job_id, proof_sequence)).status = "failed"
            db.commit()

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        if stage == "transport":
            revoke()
        before_send()
        sent.append(args)
        raise AssertionError("Revoked prerequisite cannot reach a write")

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", invoke)
    asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, job_id))
    result = ha[1].get("/api/agent-runs/" + job_id).json()
    if stage == "approval":
        assert result["status"] == "awaiting_approval", result["summary"]
        prepared = result["steps"][-1]
        revoke()
        approved = ha[1].post(
            f"/api/agent-runs/{job_id}/approve",
            headers=ha[2],
            json={
                "sequence": prepared["sequence"],
                "sha256": prepared["sha256"],
            },
        )
        assert approved.status_code == 200, approved.text
        asyncio.run(runtime.execute_agent(ha[0].state.sessions, ha[3], None, job_id))
        result = ha[1].get("/api/agent-runs/" + job_id).json()
    assert not sent and result["status"] in {"failed", "uncertain"}


def test_true_native_admin_transport_fits_and_observes_configured_prerequisite(
    ha, monkeypatch, tmp_path
):
    from test_agent_native_loop import scenario

    result, requests, calls = scenario(ha, monkeypatch, tmp_path, require_backup=True)
    assert result["status"] == "succeeded", result["summary"]
    writes = [path for _tool, method, path in calls if method == "POST"]
    assert writes == [RULE["requires"]["path"], RULE["operation"]["path"]]
    assert len([call for call in calls if call[0] == "http.verify"]) == 2
    views = [
        json.loads(body["messages"][1]["content"])["execution_state"]
        for body in requests
        if "tools" in body
    ]
    assert all(view["operation_prerequisites"][0]["requires"] == RULE["requires"] for view in views)
    assert any(not view["operation_prerequisites"][0]["satisfied"] for view in views)
    assert any(view["operation_prerequisites"][0]["satisfied"] for view in views)
