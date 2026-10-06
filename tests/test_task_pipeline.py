import json

import pytest
import test_chat
from hub.task_api import TaskSpec
from test_tasks import create


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_chat.setup.__wrapped__(tmp_path, monkeypatch)


def test_pipeline_projection_uses_fixed_nodes_and_no_private_task_payload(setup):
    app, c, h, _ = setup
    task = create(
        c,
        h,
        title="PRIVATE_TASK_TITLE",
        goal="PRIVATE_TASK_GOAL",
        include_system_reports=True,
        analysis_condition="ha_updates_available",
        steps=[{"tool_id": "ha.inspect"}, {"tool_id": "ai.analyze"}],
    )
    result = c.get("/api/tasks/" + task["id"] + "/plan").json()
    assert result["edges"] == [{"from": "step-1", "to": "step-2"}]
    assert result["nodes"][1]["condition"] == "ha_updates_available"
    assert result["model_code"] is False and result["label"] == "LOCAL_ONLY"
    assert "PRIVATE_TASK" not in json.dumps(result)
    assert all(node["context_in_n8n"] is False for node in result["nodes"])
    spec = TaskSpec(title="Old", goal="Old scope")
    assert "analysis_condition" not in spec.model_dump(mode="json")


def test_waiting_workflow_graph_has_bounded_branches_and_no_private_payload():
    import uuid

    from hub.n8n_workflows import task_workflow

    binding, task = str(uuid.uuid4()), str(uuid.uuid4())
    old = task_workflow(binding, task, 1, "header", "ca")
    graph = task_workflow(binding, task, 1, "header", "ca", wait_for_completion=True)
    assert len(old["nodes"]) == 2 and len(graph["nodes"]) == 8
    assert graph["settings"]["executionTimeout"] == 180
    assert {n["type"] for n in graph["nodes"]} == {
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.if",
        "n8n-nodes-base.wait",
        "n8n-nodes-base.noOp",
        "n8n-nodes-base.stopAndError",
    }
    requests = [n for n in graph["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    assert all(
        n["parameters"]["url"].startswith("https://192.168.117.103/api/workflow-") for n in requests
    )
    assert all(
        "goal" not in n["parameters"]["jsonBody"] and "source" not in n["parameters"]["jsonBody"]
        for n in requests
    )
    assert graph["connections"]["Bound wait"]["main"][0][0]["node"] == "Bound run status"
