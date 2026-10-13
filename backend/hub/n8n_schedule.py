"""Fixed n8n 2.7.5 clock workflow. No task content or arbitrary destinations."""

import re
from typing import Any

NAME = "obdaAI · local task clock v1"
URL = "https://192.168.117.103/api/scheduler/tick"


def clock_workflow(header_credential_id: str, ca_credential_id: str) -> dict[str, Any]:
    for value in (header_credential_id, ca_credential_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("Invalid credential identity")
    return {
        "name": NAME,
        "nodes": [
            {
                "id": "58adc845-b808-4b2d-b193-851f316b3dc9",
                "name": "Minute clock",
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.3,
                "position": [0, 0],
                "parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}},
            },
            {
                "id": "a9c76b1f-a2dd-426a-b3ba-2ecb9620d452",
                "name": "Local task pulse",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.4,
                "position": [240, 0],
                "parameters": {
                    "method": "POST",
                    "url": URL,
                    "authentication": "genericCredentialType",
                    "genericAuthType": "httpHeaderAuth",
                    "provideSslCertificates": True,
                    "sendBody": True,
                    "contentType": "json",
                    "specifyBody": "json",
                    "jsonBody": "{}",
                    "options": {
                        "timeout": 10000,
                        "allowUnauthorizedCerts": False,
                        "redirect": {"redirect": {"followRedirects": False}},
                    },
                },
                "credentials": {
                    "httpHeaderAuth": {"id": header_credential_id, "name": "obdaAI clock only"},
                    "httpSslAuth": {"id": ca_credential_id, "name": "obdaAI public CA"},
                },
            },
        ],
        "connections": {
            "Minute clock": {"main": [[{"node": "Local task pulse", "type": "main", "index": 0}]]}
        },
        "settings": {
            "timezone": "UTC",
            "executionOrder": "v1",
            "saveDataSuccessExecution": "none",
            "saveDataErrorExecution": "none",
            "saveManualExecutions": False,
            "saveExecutionProgress": False,
            "executionTimeout": 20,
        },
    }


def validate_clock_workflow(workflow: dict[str, Any], header_id: str, ca_id: str) -> None:
    expected = clock_workflow(header_id, ca_id)
    for field in ("name", "nodes", "connections"):
        if workflow.get(field) != expected[field]:
            raise ValueError("Clock workflow drift; no activation")
    settings = dict(workflow.get("settings", {}))
    for key, value in {"callerPolicy": "workflowsFromSameOwner", "availableInMCP": False}.items():
        if key in settings and settings.pop(key) != value:
            raise ValueError("Clock workflow access expanded")
    if settings != expected["settings"] or workflow.get("pinData") or workflow.get("staticData"):
        raise ValueError("Clock workflow settings or data drift")
