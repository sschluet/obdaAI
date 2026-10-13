import copy
import json
import uuid

import pytest
from hub.n8n_drafts import connection_draft, validate_connection_draft


@pytest.mark.parametrize(
    "mutation", ["code", "credential", "url", "schedule", "expression", "edge", "active"]
)
def test_only_exact_harmless_n8n_graph(mutation):
    task_id = str(uuid.uuid4())
    template = connection_draft(task_id, 1, "a" * 64)
    validate_connection_draft(template, task_id, 1, "a" * 64)
    changed = copy.deepcopy(template)
    if mutation == "code":
        changed["nodes"][1]["type"] = "n8n-nodes-base.code"
    if mutation == "credential":
        changed["nodes"][1]["credentials"] = {"httpHeaderAuth": {"id": "unsafe"}}
    if mutation == "url":
        changed["nodes"][1]["parameters"]["url"] = "http://127.0.0.1:8006"
    if mutation == "schedule":
        changed["nodes"][0]["type"] = "n8n-nodes-base.scheduleTrigger"
    if mutation == "expression":
        changed["nodes"][1]["parameters"]["value"] = "={{$env.SECRET}}"
    if mutation == "edge":
        changed["connections"]["Manual Start"]["main"][0][0]["node"] = "unknown"
    if mutation == "active":
        changed["active"] = True
    with pytest.raises(ValueError):
        validate_connection_draft(changed, task_id, 1, "a" * 64)
    encoded = json.dumps(template)
    assert "credentials" not in encoded and "http://" not in encoded and "https://" not in encoded
