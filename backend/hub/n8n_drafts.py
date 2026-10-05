"""A deliberately harmless connection-check draft, not a task execution workflow.

Only the locally verified ManualTrigger v1 -> NoOp v1 graph is emitted. No task
content, model context, URLs, credentials or schedule is sent to n8n by this module.
"""

from typing import Any
from uuid import UUID


def connection_draft(task_id: str, revision: int, spec_sha256: str) -> dict[str, Any]:
    UUID(task_id)
    if (
        revision < 1
        or len(spec_sha256) != 64
        or any(c not in "0123456789abcdef" for c in spec_sha256)
    ):
        raise ValueError("Invalid task binding")
    return {
        "name": f"obdaAI connection check {task_id} r{revision} {spec_sha256[:12]}",
        "nodes": [
            {
                "id": "7ed504e2-3a6e-4ce7-9dc8-951bb3e27389",
                "name": "Manual Start",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "parameters": {},
                "position": [0, 0],
            },
            {
                "id": "21a24a31-7e8c-4c2b-b8bc-7bd84efc07bc",
                "name": "No operation",
                "type": "n8n-nodes-base.noOp",
                "typeVersion": 1,
                "parameters": {},
                "position": [240, 0],
            },
        ],
        "connections": {
            "Manual Start": {"main": [[{"node": "No operation", "type": "main", "index": 0}]]}
        },
        "settings": {"executionOrder": "v1"},
    }


def validate_connection_draft(
    payload: dict[str, Any], task_id: str, revision: int, spec_sha256: str
) -> None:
    if payload != connection_draft(task_id, revision, spec_sha256):
        raise ValueError("Only the exact inactive connection-check template is permitted")
