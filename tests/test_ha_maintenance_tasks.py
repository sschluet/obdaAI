import json

import pytest
from hub.ha_maintenance import plan
from hub.task_api import TaskSpec
from pydantic import ValidationError
from test_tasks import control, create, run_body, setup, terminal  # noqa: F401


def reports():
    state = {
        "updates": [
            {
                "entity_id": "update.core",
                "name": "Core",
                "state": "on",
                "installed_version": "2026.9.1",
                "latest_version": "2026.9.2",
            },
            {
                "entity_id": "update.os",
                "name": "OS",
                "state": "on",
                "installed_version": "18.3",
                "latest_version": "19.0",
            },
        ],
        "label": "LOCAL_ONLY",
    }
    backup = {
        "supervisor_healthy": True,
        "supervisor_supported": True,
        "backup_state": "idle",
        "agent_error_count": 0,
        "restore_verified": True,
        "archive_integrity_verified": True,
        "recovery_key_verified": True,
        "backups": [
            {
                "id": "synthetic",
                "created": 10,
                "homeassistant_included": True,
                "database_included": True,
                "failure_count": 0,
                "copies": [{"size": 100}],
            }
        ],
    }
    return state, backup


def test_metadata_cannot_unlock_maintenance():
    report = plan(*reports())
    assert report["latest_backup_metadata"]["id"] == "synthetic"
    assert report["updates"][0]["version_change"] == "patch_candidate"
    assert report["updates"][1]["version_change"] == "separate_review"
    assert (
        not report["writes_enabled"]
        and not report["restore_verified"]
        and report["executed_changes"] == []
    )
    assert all(not row["execution_allowed"] for row in report["updates"])
    assert len(report["blockers"]) == 3


@pytest.mark.parametrize(
    "steps",
    [
        [{"tool_id": "ha.maintenance.plan"}, {"tool_id": "ai.analyze"}],
        [{"tool_id": "ha.inspect"}, {"tool_id": "ha.backups.inspect"}],
        [{"tool_id": "ha.update"}],
        [{"tool_id": "ha.inspect", "parameters": {"entity_id": "lock.frontdoor"}}],
    ],
)
def test_task_plan_never_expands_actions_or_implicitly_sends_to_model(steps):
    with pytest.raises(ValidationError):
        TaskSpec(title="Synthetic", goal="Inspect only", steps=steps)


def test_persisted_ha_task_report_and_duplicate_delivery(setup, monkeypatch):  # noqa: F811
    app, c, h, _ = setup
    calls = []

    def inspect(cfg):
        calls.append(True)
        return plan(*reports())

    monkeypatch.setattr("hub.ha_maintenance.inspect", inspect)
    task = create(
        c,
        h,
        title="Synthetic recurring HA report",
        steps=[{"tool_id": "ha.maintenance.plan"}],
        timeout_seconds=30,
    )
    task = control(c, h, task).json()
    body = run_body(task)
    result = c.post("/api/tasks/" + task["id"] + "/runs", headers=h, json=body)
    assert result.status_code == 200, result.text
    run = terminal(c, task)
    assert run["status"] == "succeeded"
    step = run["steps"][0]
    assert step["tool_id"] == "ha.maintenance.plan" and not step["result"]["writes_enabled"]
    assert (
        c.post("/api/tasks/" + task["id"] + "/runs", headers=h, json=body).json()["id"] == run["id"]
    )
    assert len(calls) == 1 and run["snapshot"]["model"] is None and run["snapshot"]["cost_usd"] == 0
    assert "Authorization" not in json.dumps(run)
