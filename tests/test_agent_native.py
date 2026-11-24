"""Native protocol preserves the canonical target and argument authority."""

import json
from copy import deepcopy

import pytest
from hub.agent_instructions import instruction
from hub.agent_native import (
    NativeCallError,
    auxiliary_parts,
    decode_calls,
    metadata_size,
    prepare,
)
from hub.agent_tools import Rules, validate_tool
from jsonschema import Draft202012Validator


def prepared(**flags):
    rows = []
    for identifier, prefix in [("one", "/api/one/"), ("two", "/api/two/")]:
        rules = Rules(
            enabled=True,
            http_methods=["GET", "POST"],
            http_prefixes=[prefix],
            ha_websocket_prefixes=["get_config", "supervisor/"],
        )
        rows.append(
            {
                "integration_id": identifier,
                "kind": "home_assistant",
                "read_only": False,
                "rules": rules.model_dump(),
                "capabilities": {"synthetic": True},
            }
        )
    data = {
        "goal": "Synthetic",
        "tools": ["http", "ha.websocket"],
        "interfaces": rows,
        "history": [],
        "clock": {"date": "2030-01-01"},
        "private_context": {"text": "private"},
        **flags,
    }
    return prepare(instruction({"home_assistant"}), data)


def call(name, arguments):
    return {
        "index": 0,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def http_binding(value, target="one"):
    return next(
        name
        for name, binding in value.metadata["bindings"].items()
        if binding.get("tool") == "http" and binding["integration_id"] == target
    )


def test_scoped_decision_and_unwrap_preserve_values():
    value = prepared()
    name = http_binding(value)
    arguments = {"method": "GET", "path": "/api/one/states", "query": {"label": "ä"}}
    for args in [arguments, {"parameters": arguments}, {"arguments": arguments}]:
        result = decode_calls(value.metadata, [call(name, args)])
        assert result is not None
        assert result["arguments"] == arguments
        assert result["integration_id"] == "one"
        normalized, effect = validate_tool(
            "home_assistant",
            Rules.model_validate(value.original_data["interfaces"][0]["rules"]),
            result["tool"],
            result["arguments"],
        )
        assert normalized["query"] == arguments["query"]
        assert not effect


@pytest.mark.parametrize(
    "arguments",
    [
        {"method": "GET", "path": "/api/two/states"},
        {"method": "GET", "path": "/api/one/states", "integration_id": "two"},
        {"parameters": {"method": "GET", "path": "/api/one/states"}, "extra": 1},
        {"parameters": {"arguments": {"method": "GET", "path": "/api/one/states"}}},
        {"parameters": {"method": "GET", "path": "/api/two/states"}},
    ],
)
def test_invalid_arguments_never_expand_scope(arguments):
    value = prepared()
    with pytest.raises(NativeCallError) as caught:
        decode_calls(value.metadata, [call(http_binding(value), arguments)])
    assert caught.value.issues == ["native_invalid_arguments"]
    assert "two" not in str(caught.value)


def test_unknown_multi_empty_and_invalid_json_are_safe():
    value = prepared()
    assert decode_calls(value.metadata, []) is None
    valid = call(http_binding(value), {"method": "GET", "path": "/api/one/states"})
    for calls in [
        [call("secret_model_name", {})],
        [valid, valid],
        [{"function": {"name": http_binding(value), "arguments": "secret invalid"}}],
        [call(http_binding(value), [])],
    ]:
        with pytest.raises(NativeCallError) as caught:
            decode_calls(value.metadata, calls)
        assert "secret" not in str(caught.value) + str(caught.value.issues)


def test_controls_match_original_flags():
    value = prepared(allow_ask=False, allow_finish=True, allow_stop=True)
    assert "ask_user" not in value.metadata["bindings"]
    for name, kind in [("finish_run", "finish"), ("stop_run", "stop")]:
        assert decode_calls(value.metadata, [call(name, {"message": "Synthetic"})]) == {
            "kind": kind,
            "message": "Synthetic",
        }
    with pytest.raises(NativeCallError):
        decode_calls(value.metadata, [call("finish_run", {"message": ""})])


def test_complete_definitions_projection_and_verification():
    value = prepared()
    definition = next(
        row["function"]
        for row in value.metadata["tools"]
        if row["function"]["name"] == http_binding(value)
    )
    validator = Draft202012Validator(definition["parameters"])
    validator.check_schema(definition["parameters"])
    validator.validate(
        {
            "method": "POST",
            "path": "/api/one/update",
            "verification": {
                "path": "/api/one/state",
                "expected": {"/body/state": "on"},
                "timeout_seconds": 120,
                "interval_seconds": 5,
            },
        }
    )
    validator.validate(
        {
            "method": "GET",
            "path": "/api/one/states",
            "projection": {
                "items_path": "",
                "where_pointer": "/entity_id",
                "where_prefix": "update.",
                "fields": ["/entity_id"],
                "limit": 10,
            },
        }
    )


def test_no_mutation_preserves_policy_private_data_and_safety():
    first = prepared()
    source = deepcopy(first.original_data)
    before = deepcopy(source)
    value = prepare(first.original_instruction, source)
    assert source == before
    assert value.original_data == before
    assert "tools" not in value.data and "decision_schema" not in value.data
    for key in ["goal", "history", "private_context", "clock"]:
        assert value.data[key] == before[key]
    for row, old in zip(value.data["interfaces"], before["interfaces"], strict=True):
        assert "rules" not in row
        assert row["policy_context"] == {
            key: val
            for key, val in old["rules"].items()
            if key not in {"http_methods", "http_prefixes", "ha_websocket_prefixes"}
        }
    for text in [
        "production_ha_approved",
        "Bei uncertain weder Ersatzaufruf",
        "untrusted Daten",
        "Nachzustand unabhängig prüfen",
    ]:
        assert text in value.instruction


def test_auxiliary_is_exact_local_tools_and_byte_count():
    value = prepared()
    parts = auxiliary_parts(value.metadata)
    assert len(parts) == 1 and str(parts[0].label) == "LOCAL_ONLY"
    assert json.loads(parts[0].content) == value.metadata["tools"]
    assert metadata_size(value.metadata) == (len(parts[0].content), len(parts[0].content.encode()))
    changed = deepcopy(value.metadata)
    changed["bindings"][http_binding(value)]["integration_id"] = "foreign"
    with pytest.raises(NativeCallError):
        decode_calls(
            changed, [call(http_binding(value), {"method": "GET", "path": "/api/one/states"})]
        )


def test_valid_root_is_never_unwrapped(monkeypatch):
    import hub.agent_native as native

    branch = {
        "properties": {
            "kind": {"const": "tool"},
            "integration_id": {"const": "one"},
            "tool": {"const": "mcp.call"},
            "arguments": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"parameters": {"type": "object"}},
                "required": ["parameters"],
            },
        },
    }
    monkeypatch.setattr(native, "decision_schema", lambda *args, **kwargs: {"anyOf": [branch]})
    value = prepared()
    args = {"parameters": {"synthetic": "unchanged"}}
    result = decode_calls(value.metadata, [call(next(iter(value.metadata["bindings"])), args)])
    assert result is not None and result["arguments"] == args


@pytest.mark.parametrize("reference", ["#/$defs/Missing", "https://example.invalid/schema"])
def test_missing_or_external_definition_rejected(monkeypatch, reference):
    import hub.agent_native as native

    branch = {
        "properties": {
            "kind": {"const": "tool"},
            "integration_id": {"const": "one"},
            "tool": {"const": "http"},
            "arguments": {"$ref": reference},
        }
    }
    monkeypatch.setattr(native, "decision_schema", lambda *args, **kwargs: {"anyOf": [branch]})
    with pytest.raises(NativeCallError):
        prepared()


def test_duplicate_json_keys_rejected():
    value = prepared()
    item = call(http_binding(value), {})
    item["function"]["arguments"] = (
        '{"method":"GET","path":"/api/two/states","path":"/api/one/states"}'
    )
    with pytest.raises(NativeCallError):
        decode_calls(value.metadata, [item])


def test_all_current_tool_kinds_compile_with_reachable_definitions():
    from hub.agent_tools import SCHEMAS

    kinds = {"ssh", "home_assistant", "paperless", "unifi", "mcp", "smtp", "gmail"}
    rules = Rules(
        enabled=True,
        shell=True,
        file_upload=True,
        private_data_to_target=True,
        gmail_read=True,
        mcp=True,
        http_prefixes=["/api/"],
        http_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        ha_websocket_prefixes=["get_config", "supervisor/"],
        file_read_roots=["/synthetic"],
        mail_recipients=["synthetic@example.invalid"],
    )
    value = prepare(
        instruction(kinds),
        {
            "tools": list(SCHEMAS),
            "interfaces": [
                {"integration_id": kind, "kind": kind, "rules": rules.model_dump()}
                for kind in sorted(kinds)
            ],
            "allow_stop": True,
        },
    )
    compiled = {row.get("tool") for row in value.metadata["bindings"].values()}
    assert set(SCHEMAS) <= compiled
    for definition in value.metadata["tools"]:
        Draft202012Validator.check_schema(definition["function"]["parameters"])


def test_descriptions_expose_exact_fixed_target_with_unavailable_leading_interface():
    value = prepared()
    data = deepcopy(value.original_data)
    data["interfaces"].insert(
        0,
        {
            "integration_id": "unavailable-first",
            "kind": "home_assistant",
            "rules": Rules(enabled=False).model_dump(),
        },
    )
    compiled = prepare(value.original_instruction, data)
    for row in compiled.metadata["tools"]:
        function = row["function"]
        binding = compiled.metadata["bindings"][function["name"]]
        if binding["kind"] == "tool":
            assert f"integration_id={binding['integration_id']}." in function["description"]
            assert "unavailable-first" not in function["description"]
    first = compiled.metadata["bindings"]["t0_http"]
    assert first["integration_id"] == "one"
