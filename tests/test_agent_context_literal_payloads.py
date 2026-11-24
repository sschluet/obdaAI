"""Model payload keys remain literal; view metadata grants no execution authority."""
from copy import deepcopy

import pytest
from hub.agent_context import _http_object_result, _observation, _websocket_result


def object_entry(tool="http", **result):
    return {
        "kind": "read", "status": "succeeded",
        "document": {"tool": tool, "arguments": {"method": "GET"}},
        "result": {"http_status": 200, "effect_verified": False, **result},
    }


def test_http_literal_scalar_keys_and_separate_audit_metadata():
    entry = object_entry(body={"huge": ["x" * 8000], "version": "1.2", "safe": False,
                               "zero": 0, "optional": None})
    original = deepcopy(entry)
    result = _http_object_result(entry, 700)
    assert result is not None
    assert result["body"] == {"version": "1.2", "safe": False, "zero": 0, "optional": None}
    assert "fields" not in result["body_view"]
    assert result["body_view"]["object_path"] == "/body"
    assert result["body_view"]["omitted_field_count"] == 1
    assert len(result["body_view"]["full_sha256"]) == 64
    assert entry == original


def test_projection_failure_and_all_control_flags_stay_failed():
    entry = object_entry(body={"huge": ["x" * 8000], "version": "1.2"},
                         projection_error="wrong shape", verification_passed=False,
                         success=False, failure_category="projection_error", error="synthetic")
    entry["status"] = "failed"
    result = _observation(entry)
    assert result["step_status"] == "failed"
    for key in ["projection_error", "effect_verified", "verification_passed", "success",
                "failure_category", "error", "http_status"]:
        assert result["result"][key] == entry["result"][key]
    assert result["result"]["body"]["version"] == "1.2"


def test_ws_object_keeps_literal_response_keys_and_bound_omissions():
    entry = object_entry("ha.websocket", response={"large": ["x" * 8000], "version": "2",
                                                  "enabled": False, "zero": 0, "nullable": None})
    original = deepcopy(entry)
    result = _websocket_result(entry, 700)
    assert result is not None
    assert result["response"]["version"] == "2" and result["response"]["enabled"] is False
    assert result["response"]["zero"] == 0 and result["response"]["nullable"] is None
    assert "fields" not in result["response_view"]
    assert result["response_view"]["object_path"] == "/response"
    assert entry == original


def test_ws_list_has_real_rows_typed_path_and_explicit_loss():
    rows = [{"entity_id": f"update.synthetic_{i}", "state": "on",
             "attributes": {"friendly_name": f"Synthetic {i}"}} for i in range(50)]
    entry = object_entry("ha.websocket", response=rows)
    original = deepcopy(entry)
    result = _websocket_result(entry, 700)
    assert result is not None
    assert result["response"] and result["response"][0] == rows[0]
    assert result["response_view"]["items_path"] == "/response"
    assert result["response_view"]["truncated"] is True
    assert result["response_view"]["observed_count"] == 50
    assert _observation(entry)["summary"]["semantic_view"]["items_path"] == "/response"
    assert entry == original


@pytest.mark.parametrize("field,value", [("success", False), ("error", "synthetic"),
                                          ("effect_verified", True)])
def test_ws_failed_or_effect_results_are_not_recast(field, value):
    entry = object_entry("ha.websocket", response={"large": ["x" * 8000]}, **{field: value})
    assert _websocket_result(entry, 700) is None
