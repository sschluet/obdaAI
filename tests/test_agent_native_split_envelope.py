"""A bounded split envelope preserves explicit values and all canonical permissions."""

import json
from copy import deepcopy

import pytest
from hub.agent_instructions import instruction
from hub.agent_native import NativeCallError, decode_calls, prepare
from hub.agent_tools import Rules, validate_tool
from test_agent_native_active_http import compiled

ARGUMENTS = {
    "method": "POST",
    "path": "/api/services/backup/create",
    "body": {"arguments": {"nested": False}, "zero": 0, "optional": None},
    "query": {"mode": "synthetic"},
    "verification": {
        "path": "/api/states/sensor.backup",
        "query": {},
        "expected": {"/body/state": "ready"},
        "timeout_seconds": 2,
        "interval_seconds": 1,
    },
}


def call(name, args):
    return [{"function": {"name": name, "arguments": json.dumps(args)}}]


def split(args=ARGUMENTS):
    return {
        "arguments": {key: deepcopy(value) for key, value in args.items() if key != "verification"},
        "verification": deepcopy(args["verification"]),
    }


@pytest.mark.parametrize("shape", ["raw", "wrapped", "split", "wrapped_split", "parameters_split"])
def test_canonical_wrapped_and_actual_double_envelope_have_identical_verified_write(shape):
    prepared, rules = compiled()
    args = deepcopy(ARGUMENTS)
    wire = {
        "raw": args,
        "wrapped": {"arguments": args},
        "split": split(args),
        "wrapped_split": {"arguments": split(args)},
        "parameters_split": {"parameters": split(args)},
    }[shape]
    original = deepcopy(wire)
    decision = decode_calls(prepared.metadata, call("t0_http_change", wire))
    assert decision["arguments"] == ARGUMENTS and wire == original
    normalized, effect = validate_tool("home_assistant", rules, "http", decision["arguments"])
    assert effect and normalized["body"] == ARGUMENTS["body"]
    assert normalized["verification"] == ARGUMENTS["verification"]


@pytest.mark.parametrize("left,right", [(False, 0), (None, {}), (0, "0"), (1, 1.0)])
def test_split_duplicate_conflicts_preserve_json_types_and_never_pick_a_value(left, right):
    prepared, _ = compiled()
    inner = deepcopy(ARGUMENTS)
    inner["body"] = {"value": left}
    wire = {"arguments": inner, "body": {"value": right}}
    with pytest.raises(NativeCallError) as caught:
        decode_calls(prepared.metadata, call("t0_http_change", wire))
    assert caught.value.issues == ["native_wrapper_conflict"]


def test_identical_duplicate_explicit_value_is_lossless_and_nested_business_data_is_untouched():
    prepared, _ = compiled()
    wire = {"arguments": deepcopy(ARGUMENTS), "body": deepcopy(ARGUMENTS["body"])}
    output = decode_calls(prepared.metadata, call("t0_http_change", wire))
    assert output["arguments"] == ARGUMENTS
    assert output["arguments"]["body"]["arguments"] == {"nested": False}


@pytest.mark.parametrize(
    "wire",
    [
        {"arguments": split(), "secret_unknown_field": "SYNTHETIC_SECRET"},
        {"arguments": {"arguments": split()}},
        {"arguments": {"arguments": {"arguments": split()}}},
        {"arguments": [ARGUMENTS], "verification": ARGUMENTS["verification"]},
        {
            "arguments": {"path": "/api/services/backup/create"},
            "verification": ARGUMENTS["verification"],
        },
        {"arguments": {"method": "POST"}, "verification": ARGUMENTS["verification"]},
    ],
)
def test_unknown_siblings_deeper_nesting_nonobjects_and_missing_fields_are_rejected(wire):
    prepared, _ = compiled()
    with pytest.raises(NativeCallError) as caught:
        decode_calls(prepared.metadata, call("t0_http_change", wire))
    assert "SYNTHETIC_SECRET" not in json.dumps(caught.value.issues)


def test_read_and_inactive_functions_cannot_gain_write_or_hidden_canonical_authority():
    prepared, _ = compiled(read_only=True)
    for name, wire in [
        ("t0_http_read", {"arguments": {"path": "/api/states"}, "method": "POST"}),
        (
            "t0_http_read",
            {
                "arguments": {
                    "arguments": {"path": "/api/states"},
                    "verification": ARGUMENTS["verification"],
                }
            },
        ),
        (
            "t0_http_project",
            {"arguments": {"method": "GET", "path": "/api/states"}, "method": "POST"},
        ),
        ("t0_http", {"arguments": split()}),
        ("t0_http_change", {"arguments": split()}),
    ]:
        with pytest.raises(NativeCallError):
            decode_calls(prepared.metadata, call(name, wire))


def test_mcp_argument_business_object_is_not_interpreted_as_split_wrapper():
    rules = Rules(enabled=True, mcp=True)
    data = {
        "goal": "Synthetic",
        "tools": ["mcp.call"],
        "history": [],
        "interfaces": [
            {"integration_id": "mcp", "kind": "mcp", "rules": rules.model_dump()},
        ],
    }
    prepared = prepare(instruction({"mcp"}), data)
    # Actual root business field 'arguments' remains an opaque object. Even an
    # invalid call cannot lift its nested name into canonical root fields.
    wire = {
        "arguments": {"name": "nested-business-name", "schema_sha256": "a" * 64},
        "schema_sha256": "a" * 64,
    }
    with pytest.raises(NativeCallError):
        decode_calls(prepared.metadata, call("t0_mcp_call", wire))


def test_real_fragmented_native_sse_decodes_actual_outer_then_split_envelope(monkeypatch, tmp_path):
    import httpx
    from test_agent_native_transport import adapter, collect, event, fragment

    prepared, _ = compiled()
    wire = json.dumps({"arguments": split()})
    midpoint = len(wire) // 2
    response = httpx.Response(
        200,
        text=event(fragment("t0_http_change", wire[:midpoint]))
        + event(fragment(arguments=wire[midpoint:]))
        + "data: [DONE]\n\n",
    )
    provider, _, requests = adapter(monkeypatch, tmp_path, response)
    provider.local_native_plan = prepared.metadata
    output = json.loads(collect(provider)[0])
    assert output["kind"] == "tool" and output["tool"] == "http"
    assert output["arguments"] == ARGUMENTS
    assert len(requests) == 1
    assert json.loads(requests[0].content)["tools"] == prepared.metadata["tools"]
