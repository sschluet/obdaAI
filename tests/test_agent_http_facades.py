"""Method-specific native views preserve exact canonical target/rules and history."""

import json
from copy import deepcopy

import pytest
from hub.agent_instructions import instruction
from hub.agent_native import NativeCallError, decode_calls, prepare, with_history
from hub.agent_tools import Rules, validate_tool


def compiled(methods=None, prefix="/api/", phase="observe", read_only=False):
    rules = Rules(enabled=True, http_methods=methods or ["GET", "POST"], http_prefixes=[prefix])
    data = {
        "goal": "Synthetic request",
        "tools": ["http"],
        "interfaces": [
            {
                "integration_id": "ha",
                "kind": "home_assistant",
                "rules": rules.model_dump(),
                "read_only": read_only,
            }
        ],
        "history": [],
        "execution_state": {"phase": phase},
        "allow_finish": False,
        "allow_ask": False,
        "allow_stop": True,
    }
    return prepare(instruction({"home_assistant"}), data), rules


def call(name, arguments):
    return [
        {
            "id": "synthetic",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps({"arguments": arguments})},
        }
    ]


def test_read_facade_has_no_method_body_or_verification_and_preserves_target():
    value, rules = compiled()
    wire = next(
        t["function"] for t in value.metadata["tools"] if t["function"]["name"] == "t0_http_read"
    )
    assert set(wire["parameters"]["properties"]["arguments"]["properties"]) == {"path", "query"}
    decision = decode_calls(value.metadata, call("t0_http_read", {"path": "/api/config"}))
    assert decision["integration_id"] == "ha" and decision["tool"] == "http"
    args, effect = validate_tool("home_assistant", rules, "http", decision["arguments"])
    assert args["method"] == "GET" and not effect
    for arguments in [
        {"path": "/outside/"},
        {"path": "/api/webhook/synthetic"},
        {"path": "/API/WEBHOOK/synthetic"},
        {"path": "/api/config", "method": "POST"},
        {"path": "/api/config", "body": {"secret": "synthetic"}},
    ]:
        with pytest.raises(NativeCallError):
            decode_calls(value.metadata, call("t0_http_read", arguments))


def test_change_facade_keeps_verification_exact_and_never_infers_missing_values():
    value, rules = compiled(phase="act")
    assert value.metadata["tools"][0]["function"]["name"] == "t0_http_change"
    arguments = {
        "method": "POST",
        "path": "/api/services/example/change",
        "body": {"value": False},
        "verification": {"path": "/api/states/sensor.synthetic", "expected": {"/body/state": "ok"}},
    }
    original = deepcopy(arguments)
    decision = decode_calls(value.metadata, call("t0_http_change", arguments))
    assert decision["arguments"] == original and arguments == original
    assert validate_tool("home_assistant", rules, "http", decision["arguments"])[1]
    with pytest.raises(NativeCallError):
        decode_calls(value.metadata, call("t0_http_change", {"path": "/api/"}))
    with pytest.raises(NativeCallError):
        decode_calls(value.metadata, call("t0_http_change", {"path": "/api/", "method": "DELETE"}))


def test_read_only_and_webhook_only_policies_do_not_offer_change_or_fake_read():
    read, _ = compiled(methods=["GET"], read_only=True)
    assert "t0_http_read" in read.metadata["bindings"]
    assert "t0_http_change" not in read.metadata["bindings"]
    webhook, _ = compiled(methods=["GET"], prefix="/api/webhook/")
    assert "t0_http_read" not in webhook.metadata["bindings"]


def test_history_is_reconstructed_using_canonical_not_convenience_wire():
    value, _ = compiled()
    data = deepcopy(value.original_data)
    arguments = {"method": "GET", "path": "/api/config"}
    data["history"] = [
        {
            "sequence": 1,
            "kind": "read",
            "status": "succeeded",
            "document": {"integration_id": "ha", "tool": "http", "arguments": arguments},
            "result": {"http_status": 200, "body": {"version": "synthetic"}},
        }
    ]
    value = prepare(instruction({"home_assistant"}), data)
    native, _ = with_history(value, value.data)
    call_value = native.metadata["messages"][0]["tool_calls"][0]
    assert call_value["function"]["name"] == "t0_http_read"
    assert json.loads(call_value["function"]["arguments"])["arguments"] == {"path": "/api/config"}


def test_active_views_cannot_be_dropped_to_reexpose_private_complex_schema():
    from hub.agent_native import without_http_facades

    value, _ = compiled()
    minimal = without_http_facades(value)
    assert minimal == value
    assert "t0_http" not in {row["function"]["name"] for row in minimal.metadata["tools"]}
    assert minimal.metadata["canonical_tools"]
    with pytest.raises(NativeCallError):
        decode_calls(minimal.metadata, call("t0_http", {"method": "GET", "path": "/api/"}))
    assert decode_calls(minimal.metadata, call("t0_http_read", {"path": "/api/config"}))
