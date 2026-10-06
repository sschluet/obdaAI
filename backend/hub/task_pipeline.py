"""Code-owned workflow projection, with no model code or private payload in n8n."""

from typing import Any

from hub.task_api import TaskSpec

LABELS = {
    "hub.inspect": "Arbeitsraum prüfen",
    "ha.inspect": "Home-Assistant-Status lesen",
    "ha.backups.inspect": "HA-Sicherungsmetadaten lesen",
    "ha.maintenance.plan": "HA-Wartungsbericht lesen",
    "ai.analyze": "Lokal auswerten",
    "project.archive": "Gebundenes Projekt archivieren",
}


def plan(spec: TaskSpec) -> dict[str, Any]:
    nodes = []
    for sequence, step in enumerate(spec.steps, 1):
        nodes.append(
            {
                "id": "step-" + str(sequence),
                "sequence": sequence,
                "tool_id": step.tool_id,
                "tool_revision": step.tool_revision,
                "name": LABELS[step.tool_id],
                "effect": "write"
                if step.tool_id == "project.archive"
                else "model"
                if step.tool_id == "ai.analyze"
                else "read",
                "condition": spec.analysis_condition if step.tool_id == "ai.analyze" else "always",
                "label": "LOCAL_ONLY",
                "context_in_n8n": False,
            }
        )
    return {
        "version": 1,
        "nodes": nodes,
        "edges": [
            {"from": nodes[i]["id"], "to": nodes[i + 1]["id"]} for i in range(len(nodes) - 1)
        ],
        "include_system_reports": spec.include_system_reports,
        "execution": "local_bound_task_gateway",
        "n8n_payload": "dispatch_and_execution_identifiers_only",
        "model_code": False,
        "label": "LOCAL_ONLY",
    }
