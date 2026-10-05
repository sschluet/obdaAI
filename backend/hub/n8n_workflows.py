"""Code-owned execution template. Private task context never enters n8n."""

import re
from typing import Any
from uuid import UUID

from hub.n8n_check import CheckError, remote_check

ORIGIN = "https://192.168.117.103"


def task_workflow(
    binding_id: str, task_id: str, revision: int, header_id: str, ca_id: str
) -> dict[str, Any]:
    UUID(binding_id)
    UUID(task_id)
    if revision < 1 or any(
        not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v) for v in (header_id, ca_id)
    ):
        raise ValueError("Invalid workflow binding")
    return {
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
                    "jsonBody": ("={{ JSON.stringify({dispatch_id: $json.body.dispatch_id, "
                                 "execution_id: $execution.id}) }}"),
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
