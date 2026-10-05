from copy import deepcopy

import pytest
from hub.n8n_schedule import clock_workflow, validate_clock_workflow


def test_clock_has_fixed_local_endpoint_no_context_and_strict_tls():
    flow = clock_workflow("synthetic-header", "synthetic-ca")
    validate_clock_workflow(flow, "synthetic-header", "synthetic-ca")
    node = flow["nodes"][1]["parameters"]
    assert node["jsonBody"] == "{}"
    assert not node["options"]["allowUnauthorizedCerts"]
    assert not node["options"]["redirect"]["redirect"]["followRedirects"]
    assert len(flow["nodes"]) == 2
    for field, value in [
        ("url", "https://attacker.example"),
        ("jsonBody", '{"goal":"private"}'),
        ("authentication", "none"),
    ]:
        changed = deepcopy(flow)
        changed["nodes"][1]["parameters"][field] = value
        with pytest.raises(ValueError):
            validate_clock_workflow(changed, "synthetic-header", "synthetic-ca")
    changed = deepcopy(flow)
    changed["settings"]["callerPolicy"] = "any"
    with pytest.raises(ValueError):
        validate_clock_workflow(changed, "synthetic-header", "synthetic-ca")
    with pytest.raises(ValueError):
        clock_workflow("expression={{token}}", "ca")
