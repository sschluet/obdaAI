"""Code-owned execution template. Private task context never enters n8n."""

import copy
import re
from typing import Any
from uuid import UUID

from hub.n8n_check import CheckError, remote_check

ORIGIN = "https://192.168.117.103"


def task_workflow(
    binding_id: str,
    task_id: str,
    revision: int,
    header_id: str,
    ca_id: str,
    *,
    wait_for_completion: bool = False,
) -> dict[str, Any]:
    UUID(binding_id)
    UUID(task_id)
    if revision < 1 or any(
        not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v) for v in (header_id, ca_id)
    ):
        raise ValueError("Invalid workflow binding")
    graph: dict[str, Any] = {
        "name": f"obdaAI task {task_id} r{revision} {binding_id}",
        "nodes": [
            {
                "id": "51a7f64e-e2f9-4efe-9306-3de7d427e092",
                "name": "Task request",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2.1,
                "position": [0, 0],
                "webhookId": binding_id,
                "parameters": {
                    "httpMethod": "POST",
                    "path": "obdaai-" + binding_id,
                    "authentication": "headerAuth",
                    "responseMode": "lastNode",
                    "options": {},
                },
                "credentials": {
                    "httpHeaderAuth": {"id": header_id, "name": "obdaAI task " + binding_id}
                },
            },
            {
                "id": "59e6aef0-a9c6-418d-b278-e84423e9b145",
                "name": "Bound task gateway",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.4,
                "position": [240, 0],
                "parameters": {
                    "method": "POST",
                    "url": ORIGIN + "/api/workflow-callback/" + binding_id,
                    "authentication": "genericCredentialType",
                    "genericAuthType": "httpHeaderAuth",
                    "provideSslCertificates": True,
                    "sendBody": True,
                    "contentType": "json",
                    "specifyBody": "json",
                    "jsonBody": (
                        "={{ JSON.stringify({dispatch_id: $json.body.dispatch_id, "
                        "execution_id: $execution.id}) }}"
                    ),
                    "options": {
                        "timeout": 10000,
                        "allowUnauthorizedCerts": False,
                        "redirect": {"redirect": {"followRedirects": False}},
                    },
                },
                "credentials": {
                    "httpHeaderAuth": {"id": header_id, "name": "obdaAI task " + binding_id},
                    "httpSslAuth": {"id": ca_id, "name": "obdaAI public CA"},
                },
            },
        ],
        "connections": {
            "Task request": {"main": [[{"node": "Bound task gateway", "type": "main", "index": 0}]]}
        },
        "settings": {
            "executionOrder": "v1",
            "timezone": "UTC",
            "saveDataSuccessExecution": "none",
            "saveDataErrorExecution": "none",
            "saveManualExecutions": False,
            "saveExecutionProgress": False,
            "executionTimeout": 30,
        },
    }
    if wait_for_completion:
        status = copy.deepcopy(graph["nodes"][1])
        status.update(
            {
                "id": "f2bca9dd-0e93-4104-97f2-7cc84ff90c08",
                "name": "Bound run status",
                "position": [480, 0],
            }
        )
        status["parameters"]["url"] = ORIGIN + "/api/workflow-status/" + binding_id
        status["parameters"]["jsonBody"] = (
            '={{ JSON.stringify({dispatch_id: $("Task request").first().json.body.dispatch_id, '
            "execution_id: $execution.id}) }}"
        )

        def condition(name: str, identity: str, value: str, position: list[int]) -> dict[str, Any]:
            return {
                "id": identity,
                "name": name,
                "type": "n8n-nodes-base.if",
                "typeVersion": 2.2,
                "position": position,
                "parameters": {
                    "conditions": {
                        "options": {
                            "caseSensitive": True,
                            "leftValue": "",
                            "typeValidation": "strict",
                            "version": 2,
                        },
                        "conditions": [
                            {
                                "id": identity,
                                "leftValue": "={{ $json." + value + " }}",
                                "rightValue": True,
                                "operator": {
                                    "type": "boolean",
                                    "operation": "true",
                                    "singleValue": True,
                                },
                            }
                        ],
                        "combinator": "and",
                    },
                    "options": {},
                },
            }

        complete = condition(
            "Run complete", "a7b5740f-8085-4c1f-8a56-6e0120086059", "complete", [720, 0]
        )
        successful = condition(
            "Run succeeded", "c22583b6-b597-4880-8622-e2af21d1cd4d", "succeeded", [960, -100]
        )
        wait = {
            "id": "c0a7ae0e-f3a4-4cd0-b9d3-68f4c40ee0c5",
            "name": "Bound wait",
            "type": "n8n-nodes-base.wait",
            "typeVersion": 1.1,
            "position": [960, 120],
            "parameters": {"resume": "timeInterval", "amount": 5, "unit": "seconds"},
        }
        done = {
            "id": "182e7d90-e5d9-4935-ae54-743b5f33c020",
            "name": "Complete",
            "type": "n8n-nodes-base.noOp",
            "typeVersion": 1,
            "position": [1200, -180],
            "parameters": {},
        }
        failed = {
            "id": "71948d6d-5b74-4800-bb6a-40ab5c83f290",
            "name": "Bound failure",
            "type": "n8n-nodes-base.stopAndError",
            "typeVersion": 1,
            "position": [1200, 0],
            "parameters": {
                "errorType": "errorMessage",
                "errorMessage": "Bound obdaAI task did not succeed; inspect Task-Center.",
            },
        }
        graph["nodes"].extend([status, complete, successful, wait, done, failed])

        def edge(name: str) -> list[dict[str, Any]]:
            return [{"node": name, "type": "main", "index": 0}]

        graph["connections"].update(
            {
                "Bound task gateway": {"main": [edge("Bound run status")]},
                "Bound run status": {"main": [edge("Run complete")]},
                "Run complete": {"main": [edge("Run succeeded"), edge("Bound wait")]},
                "Bound wait": {"main": [edge("Bound run status")]},
                "Run succeeded": {"main": [edge("Complete"), edge("Bound failure")]},
            }
        )
        graph["settings"]["executionTimeout"] = 180
    return graph


def verify_workflow(
    remote: dict[str, Any], expected: dict[str, Any], *, active: bool, version: str | None = None
) -> str:
    # Reuse the exact graph/settings validation, normalizing only lifecycle metadata.
    if remote.get("active") is not active or remote.get("isArchived", False):
        raise CheckError("Workflow lifecycle drift")
    if version and remote.get("versionId") != version:
        raise CheckError("Workflow version drift")
    if active and remote.get("activeVersionId") != remote.get("versionId"):
        raise CheckError("Published workflow version drift")
    checked = {**remote, "active": False, "activeVersionId": None}
    return remote_check(checked, expected)
