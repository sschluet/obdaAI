"""Only simple active HTTP tools are callable; originals stay private and hash-bound."""

import json
from copy import deepcopy

import pytest
from hub.agent_context import project
from hub.agent_http_facades import normalized_http
from hub.agent_instructions import instruction
from hub.agent_native import (
    NativeCallError,
    _digest,
    auxiliary_parts,
    decode_calls,
    metadata_size,
    native_messages,
    prepare,
    with_history,
)
from hub.agent_tools import HTTPCall, Rules, validate_tool


def compiled(*, read_only=False, methods=None):
    rules = Rules(
        enabled=True,
        http_prefixes=["/api/"],
        http_methods=methods or (["GET"] if read_only else ["GET", "POST", "PATCH"]),
    )
    data = {
        "goal": "Synthetic goal",
        "tools": ["http"],
        "interfaces": [
            {
                "integration_id": "ha",
                "kind": "home_assistant",
                "read_only": read_only,
                "rules": rules.model_dump(),
            }
        ],
        "read_only": read_only,
        "history": [],
        "allow_finish": False,
        "allow_ask": False,
    }
    return prepare(instruction({"home_assistant"}), data), rules


def call(name, args):
    return [
        {
            "type": "function",
            "function": {"name": name, "arguments": json.dumps({"arguments": args})},
        }
    ]


def test_complex_original_is_private_uncallable_and_not_in_model_budget():
    value, _ = compiled()
    names = [row["function"]["name"] for row in value.metadata["tools"]]
    assert "t0_http" not in names
    assert set(names) == {"t0_http_read", "t0_http_change", "t0_http_project"}
    assert value.metadata["canonical_tools"][0]["function"]["name"] == "t0_http"
    with pytest.raises(NativeCallError) as caught:
        decode_calls(value.metadata, call("t0_http", {"method": "GET", "path": "/api/config"}))
    assert "native_unoffered_function" in caught.value.issues
    altered = deepcopy(value.metadata)
    altered["canonical_tools"][0]["function"]["description"] += "PRIVATE_ONLY_SCHEMA_SENTINEL"
    assert metadata_size(altered) == metadata_size(value.metadata)
    assert all("PRIVATE_ONLY_SCHEMA_SENTINEL" not in p.content for p in auxiliary_parts(altered))
    assert _digest(altered) != value.metadata["sha256"]
    with pytest.raises(NativeCallError) as caught:
        decode_calls(altered, call("t0_http_read", {"path": "/api/config"}))
    assert "native_metadata_invalid" in caught.value.issues


@pytest.mark.parametrize(
    "mode,value",
    [
        ("equals", None),
        ("equals", False),
        ("equals", 0),
        ("equals", "0"),
        ("prefix", "pre"),
        ("none", None),
    ],
)
def test_flat_projection_preserves_exact_predicate_types(mode, value):
    native, rules = compiled(read_only=True)
    args = {
        "method": "GET",
        "path": "/api/states",
        "filter_mode": mode,
        "filter_field": "" if mode == "none" else "/value",
        "filter_value": value,
        "fields": ["/value"],
        "items_path": "",
        "limit": 100,
    }
    decision = decode_calls(native.metadata, call("t0_http_project", args))
    normalized, effect = validate_tool("home_assistant", rules, "http", decision["arguments"])
    assert not effect
    rows = [{"value": v} for v in [None, False, 0, "0", "prefix"]]
    result = project(rows, normalized["projection"])
    if mode == "none":
        assert result["matched"] == 5
    elif mode == "prefix":
        assert result["items"] == [{"/value": "prefix"}]
    else:
        assert result["matched"] == 1
        assert type(result["items"][0]["/value"]) is type(value)
        assert result["items"][0]["/value"] == value


@pytest.mark.parametrize(
    "change",
    [
        lambda a: a.pop("filter_field"),
        lambda a: a.update(filter_field=None),
        lambda a: a.update(filter_mode="guess"),
        lambda a: a.update(filter_value=False),
        lambda a: a.update(method="DELETE"),
        lambda a: a.update(path="/outside/"),
    ],
)
def test_advanced_projection_never_guesses_or_bypasses_scopes(change):
    value, _ = compiled(read_only=True)
    args = {
        "method": "GET",
        "path": "/api/states",
        "filter_mode": "prefix",
        "filter_field": "/entity_id",
        "filter_value": "update.",
    }
    change(args)
    with pytest.raises(NativeCallError):
        decode_calls(value.metadata, call("t0_http_project", args))


def test_history_prefers_lossless_simple_aliases_but_original_db_documents_stay_literal():
    value, _ = compiled()
    originals = [
        HTTPCall(method="GET", path="/api/config").model_dump(mode="json"),
        HTTPCall(
            method="POST",
            path="/api/services/example/change",
            query={"n": 0, "b": False},
            body={"n": 0, "b": False},
            verification={
                "path": "/api/states/sensor.synthetic",
                "expected": {"/body/state": "on"},
            },
        ).model_dump(mode="json"),
        HTTPCall(
            method="GET",
            path="/api/states",
            projection={"where_pointer": "/value", "where_equals": False, "fields": ["/value"]},
        ).model_dump(mode="json"),
    ]
    data = deepcopy(value.data)
    data["history"] = [
        {
            "sequence": i,
            "kind": "effect" if i == 2 else "read",
            "status": "succeeded",
            "document": {"integration_id": "ha", "tool": "http", "arguments": args},
            "result": {"http_status": 200, "body": {"synthetic": True}},
        }
        for i, args in enumerate(originals, 1)
    ]
    before = deepcopy(data)
    prepared, _ = with_history(value, data)
    messages = native_messages(prepared.metadata)
    names = [m["tool_calls"][0]["function"]["name"] for m in messages if m["role"] == "assistant"]
    assert names == ["t0_http_read", "t0_http_change", "t0_http_project"]
    for message, original in zip(messages[::2], originals, strict=True):
        decision = decode_calls(prepared.metadata, message["tool_calls"])
        assert normalized_http(decision["arguments"]) == normalized_http(original)
    assert data == before


def test_all_existing_http_methods_keep_body_verification_and_post_projection():
    value, rules = compiled(methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    for method in ["POST", "PUT", "PATCH", "DELETE"]:
        args = {
            "method": method,
            "path": "/api/example",
            "body": {"b": False, "n": 0},
            "verification": {
                "path": "/api/states/sensor.synthetic",
                "expected": {"/body/value": False},
            },
            "filter_mode": "none",
            "filter_field": "",
            "filter_value": None,
        }
        decision = decode_calls(value.metadata, call("t0_http_project", args))
        actual, effect = validate_tool("home_assistant", rules, "http", decision["arguments"])
        assert effect and actual["body"] == {"b": False, "n": 0}
        assert actual["verification"]["expected"] == {"/body/value": False}
        assert actual["projection"]["where_pointer"] is None


def test_native_prose_describes_only_active_flat_projection_legacy_unchanged():
    value, _ = compiled()
    assert "filter_mode=none|equals|prefix" in value.instruction
    assert "filter_field" in value.instruction
    assert "Große Antworten: projection mit" not in value.instruction
    assert "where_pointer" not in value.instruction
    assert "where_prefix" not in value.instruction
    assert "Große Antworten: projection mit" in value.original_instruction
    assert value.original_instruction == instruction({"home_assistant"})


def test_actual_native_transport_sends_only_active_wire_and_reversible_history(
    monkeypatch, tmp_path
):
    import asyncio

    import httpx
    from hub.policy import ContextPart
    from test_agent_native_transport import adapter, event, fragment

    source, _ = compiled(read_only=True)
    fitted = deepcopy(source.data)
    fitted["history"] = [
        {
            "sequence": 1,
            "kind": "read",
            "status": "succeeded",
            "document": {
                "integration_id": "ha",
                "tool": "http",
                "arguments": {"method": "GET", "path": "/api/config"},
            },
            "result": {"http_status": 200, "body": {"version": "synthetic"}},
        }
    ]
    source, _ = with_history(source, fitted)
    response = httpx.Response(
        200,
        text=event(
            fragment(
                "t0_http_read",
                '{"arguments":{"path":"/api/states"}}',
            )
        )
        + "data: [DONE]\n\n",
    )
    provider, _, requests = adapter(monkeypatch, tmp_path, response)
    provider.local_native_plan = source.metadata

    async def run():
        return [
            piece
            async for piece in provider.stream(
                [ContextPart(content="Synthetic input", source_id="synthetic", revision=1)],
                ["user"],
                external=False,
                grants=[],
            )
        ]

    result = json.loads(asyncio.run(run())[0])
    assert result["tool"] == "http" and result["arguments"] == {
        "method": "GET",
        "path": "/api/states",
    }
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert "canonical_tools" not in body
    assert body["tools"] == source.metadata["tools"]
    assert "t0_http" not in {row["function"]["name"] for row in body["tools"]}
    assert body["messages"][1]["tool_calls"][0]["function"]["name"] == "t0_http_read"
    assert body["messages"][2]["tool_call_id"] == body["messages"][1]["tool_calls"][0]["id"]


def test_websocket_only_native_prose_does_not_promise_http_selection():
    source, _ = compiled(read_only=True)
    data = deepcopy(source.original_data)
    data["tools"] = ["ha.websocket"]
    data["interfaces"][0]["rules"]["ha_websocket_prefixes"] = ["get_"]
    value = prepare(instruction({"home_assistant"}), data)
    assert not any(binding.get("tool") == "http" for binding in value.metadata["bindings"].values())
    assert "filter_field" not in value.instruction
    assert "where_pointer" not in value.instruction
    assert "HTTP: registrierter" not in value.instruction
    assert "/api/states-Liste" not in value.instruction
    assert value.original_instruction == instruction({"home_assistant"})


@pytest.mark.parametrize(
    "mode,field,value",
    [
        ("none", "/value", None),
        ("none", "", False),
        ("none", "", 0),
        ("equals", "", None),
        ("prefix", "", ""),
        ("prefix", "/value", False),
        ("prefix", "/value", 0),
        ("prefix", "/value", None),
    ],
)
def test_flat_selector_rejects_contradictory_or_missing_predicate(mode, field, value):
    source, _ = compiled(read_only=True)
    with pytest.raises(NativeCallError):
        decode_calls(
            source.metadata,
            call(
                "t0_http_project",
                {
                    "method": "GET",
                    "path": "/api/states",
                    "filter_mode": mode,
                    "filter_field": field,
                    "filter_value": value,
                },
            ),
        )


def test_flat_prefix_retains_canonically_supported_empty_string():
    source, _ = compiled(read_only=True)
    decision = decode_calls(
        source.metadata,
        call(
            "t0_http_project",
            {
                "method": "GET",
                "path": "/api/states",
                "filter_mode": "prefix",
                "filter_field": "/entity_id",
                "filter_value": "",
            },
        ),
    )
    assert decision["arguments"]["projection"]["where_prefix"] == ""
