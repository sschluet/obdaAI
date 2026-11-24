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
    assert caught.value.issues[0] == "args_schema_invalid"
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
            "arguments": {
                "method": "POST",
                "path": "/api/one/update",
                "verification": {
                    "path": "/api/one/state",
                    "expected": {"/body/state": "on"},
                    "timeout_seconds": 120,
                    "interval_seconds": 5,
                },
            }
        }
    )
    validator.validate(
        {
            "arguments": {
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


@pytest.mark.parametrize(
    "case,expected",
    [
        ("unknown", "native_unknown_function"),
        ("multiple", "native_call_count"),
        ("json", "native_invalid_json"),
        ("duplicate", "native_duplicate_json_keys"),
        ("schema", "args_schema_invalid"),
    ],
)
def test_safe_protocol_diagnostics_distinguish_failure_without_model_values(case, expected):
    value = prepared()
    name = http_binding(value)
    private = "SYNTHETIC_PRIVATE_PATH_TOKEN"
    args = {"method": "GET", "path": "/api/one/states"}
    item = call(name, args)
    calls = [item]
    if case == "unknown":
        item["function"]["name"] = private
    elif case == "multiple":
        calls.append(call(name, {"method": private}))
    elif case == "json":
        item["function"]["arguments"] = '{"secret":' + private
    elif case == "duplicate":
        item["function"]["arguments"] = '{"' + private + '":1,"' + private + '":2}'
    else:
        item["function"]["arguments"] = json.dumps({"method": private, private: private})
    with pytest.raises(NativeCallError) as caught:
        decode_calls(value.metadata, calls)
    issues = caught.value.issues
    assert issues[0] == expected
    assert 1 <= len(issues) <= 6 and all(len(issue) <= 120 for issue in issues)
    assert private not in str(caught.value) + json.dumps(issues)
    if case == "schema":
        assert "required:path" in issues
        assert any(issue.startswith("schema:") for issue in issues)


def test_anyof_schema_diagnostics_use_only_trusted_keywords_and_missing_fields(monkeypatch):
    import hub.agent_native as native

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "projection": {
                "anyOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"items_path": {"type": "string"}},
                        "required": ["items_path"],
                    },
                    {"type": "null"},
                ]
            }
        },
        "required": ["projection"],
    }
    branch = {
        "properties": {
            "kind": {"const": "tool"},
            "integration_id": {"const": "one"},
            "tool": {"const": "http"},
            "arguments": schema,
        }
    }
    monkeypatch.setattr(native, "decision_schema", lambda *a, **kw: {"anyOf": [branch]})
    value = prepared()
    name = next(iter(value.metadata["bindings"]))
    secret = "PRIVATE_UNKNOWN_KEY_AND_VALUE"
    with pytest.raises(NativeCallError) as caught:
        decode_calls(value.metadata, [call(name, {"projection": {secret: secret}})])
    assert "schema:anyOf" in caught.value.issues
    assert "required:items_path" in caught.value.issues
    assert "schema:additionalProperties" in caught.value.issues
    assert secret not in str(caught.value) + json.dumps(caught.value.issues)
    # Both invalid outer args and the existing sole-wrapper variant remain closed.
    with pytest.raises(NativeCallError) as wrapped:
        decode_calls(value.metadata, [call(name, {"parameters": {"projection": {secret: secret}}})])
    assert wrapped.value.issues == caught.value.issues


def test_schema_issue_volume_and_names_are_bounded(monkeypatch):
    import hub.agent_native as native

    fields = {"field_" + str(i): {"type": "string"} for i in range(100)}
    branch = {
        "properties": {
            "kind": {"const": "tool"},
            "integration_id": {"const": "one"},
            "tool": {"const": "http"},
            "arguments": {
                "type": "object",
                "properties": fields,
                "required": list(fields),
            },
        }
    }
    monkeypatch.setattr(native, "decision_schema", lambda *a, **kw: {"anyOf": [branch]})
    value = prepared()
    with pytest.raises(NativeCallError) as caught:
        decode_calls(value.metadata, [call(next(iter(value.metadata["bindings"])), {})])
    assert len(caught.value.issues) == 6
    assert caught.value.issues[:2] == ["args_schema_invalid", "schema:required"]
    assert all(issue.startswith("required:field_") for issue in caught.value.issues[2:])


def test_native_instruction_requires_one_call_and_existing_evidence_for_completion():
    value = prepared()
    for text in [
        "GENAU EINEN Funktionsaufruf",
        "Warte dessen Ergebnis ab",
        "keine parallelen Aufrufe",
        "Abschluss nur aus bereits vorliegenden Belegen",
    ]:
        assert text in value.instruction
    assert "Nachzustand unabhängig prüfen" in value.instruction
    assert "Bei uncertain weder Ersatzaufruf" in value.instruction


def test_tool_wire_is_one_object_with_hoisted_refs_and_typed_nested_values():
    value = prepared()
    name = http_binding(value)
    function = next(
        row["function"] for row in value.metadata["tools"] if row["function"]["name"] == name
    )
    wire = function["parameters"]
    assert wire["type"] == "object" and wire["additionalProperties"] is False
    assert wire["required"] == ["arguments"] and set(wire["properties"]) == {"arguments"}
    assert wire["properties"]["arguments"]["type"] == "object"
    assert "$defs" in wire and "$defs" not in wire["properties"]["arguments"]
    assert "#/$defs/" in json.dumps(wire["properties"]["arguments"])
    assert value.metadata["bindings"][name]["argument_object"] is True
    examples = [
        {
            "method": "GET",
            "path": "/api/one/states",
            "query": {"enabled": True, "limit": 10},
            "body": None,
            "projection": {
                "items_path": "",
                "where_pointer": "/entity_id",
                "where_prefix": "update.",
                "where_equals": None,
                "fields": ["/entity_id", "/state"],
                "limit": 100,
            },
            "verification": None,
        },
        {
            "method": "POST",
            "path": "/api/one/update",
            "query": {"dry_run": False},
            "body": {"enabled": True, "optional": None, "items": [1, False, {"value": None}]},
            "projection": None,
            "verification": None,
        },
    ]
    for arguments in examples:
        Draft202012Validator(wire).validate({"arguments": arguments})
        for actual in [arguments, {"arguments": arguments}]:
            result = decode_calls(value.metadata, [call(name, actual)])
            assert result is not None and result["arguments"] == arguments
            assert type(result["arguments"]["query"][next(iter(arguments["query"]))]) is bool
            assert result["integration_id"] == "one"
    assert "arguments als vollständiges JSON-Objekt" in value.instruction
    assert "direkt message" in value.instruction


@pytest.mark.parametrize("field", ["projection", "body", "query"])
def test_stringified_objects_are_not_silently_repaired(field):
    value = prepared()
    arguments = {"method": "GET", "path": "/api/one/states", field: '{"private":true}'}
    with pytest.raises(NativeCallError) as caught:
        decode_calls(value.metadata, [call(http_binding(value), {"arguments": arguments})])
    assert caught.value.issues[0] == "args_schema_invalid"
    assert "private" not in str(caught.value.issues)


def test_historical_metadata_v1_without_argument_object_remains_compatible():
    from hub.agent_native import _digest

    value = prepared()
    historical = deepcopy(value.metadata)
    for row in historical["tools"]:
        function = row["function"]
        binding = historical["bindings"][function["name"]]
        if binding.pop("argument_object", False):
            wire = function["parameters"]
            canonical = deepcopy(wire["properties"]["arguments"])
            if "$defs" in wire:
                canonical["$defs"] = deepcopy(wire["$defs"])
            if "anyOf" in canonical:
                canonical.pop("type", None)
            function["parameters"] = canonical
    historical["sha256"] = _digest(historical)
    assert historical["version"] == 1
    arguments = {
        "method": "GET",
        "path": "/api/one/states",
        "body": None,
        "query": {"enabled": False},
    }
    for actual in [arguments, {"parameters": arguments}, {"arguments": arguments}]:
        result = decode_calls(historical, [call(http_binding(value), actual)])
        assert result is not None and result["arguments"] == arguments
    assert decode_calls(historical, [call("finish_run", {"message": "Synthetic evidence"})]) == {
        "kind": "finish",
        "message": "Synthetic evidence",
    }
    tampered = deepcopy(value.metadata)
    tampered["bindings"][http_binding(value)].pop("argument_object")
    with pytest.raises(NativeCallError) as caught:
        decode_calls(tampered, [call(http_binding(value), arguments)])
    assert caught.value.issues == ["native_metadata_invalid"]


def test_new_wire_control_functions_keep_direct_message():
    value = prepared(allow_ask=True, allow_finish=True, allow_stop=True)
    for name in ["ask_user", "finish_run", "stop_run"]:
        function = next(
            row["function"] for row in value.metadata["tools"] if row["function"]["name"] == name
        )
        assert set(function["parameters"]["properties"]) == {"message"}
        assert "argument_object" not in value.metadata["bindings"][name]
        result = decode_calls(value.metadata, [call(name, {"message": "Synthetic"})])
        assert result is not None and result["message"] == "Synthetic"
