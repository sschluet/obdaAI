"""Semantic HA entity reads remain ordinary scoped HTTP decisions, not new authority."""

import json
from copy import deepcopy

import pytest
from hub.agent_instructions import instruction
from hub.agent_native import (
    NativeCallError,
    _digest,
    decode_calls,
    native_messages,
    prepare,
    with_history,
)
from hub.agent_read_projection import narrow_entity_read
from hub.agent_tools import Rules, validate_tool
from jsonschema import Draft202012Validator


def build(
    *,
    kind="home_assistant",
    enabled=True,
    methods=None,
    prefixes=None,
    domain="update",
    missing_target="ha",
    evidence=True,
    leading_disabled=False,
):
    rules = Rules(
        enabled=enabled,
        http_methods=methods or ["GET", "POST"],
        http_prefixes=prefixes or ["/api/"],
    )
    interfaces = [
        {"integration_id": "ha", "kind": kind, "read_only": True, "rules": rules.model_dump()}
    ]
    if leading_disabled:
        interfaces.insert(
            0,
            {
                "integration_id": "disabled",
                "kind": kind,
                "rules": Rules(enabled=False).model_dump(),
            },
        )
    data = {
        "goal": "Synthetic entity inventory",
        "interfaces": interfaces,
        "tools": ["http"],
        "read_only": True,
        "history": [],
        "goal_evidence": {
            "missing": [
                {"kind": "entity_states", "domain": domain, "integration_id": missing_target}
            ]
            if evidence
            else []
        },
    }
    before = deepcopy(data)
    result = prepare(instruction({kind}), data)
    assert data == before
    return result, rules


def facade(value):
    return next(name for name in value.metadata["bindings"] if name.endswith("_ha_entities"))


def call(name, arguments):
    return {"type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


@pytest.mark.parametrize("domain", ["update", "light", "sensor"])
def test_entity_function_is_preferred_but_returns_only_scoped_canonical_http(domain):
    value, rules = build(domain=domain)
    name = facade(value)
    assert value.metadata["tools"][0]["function"]["name"] == name
    binding = value.metadata["bindings"][name]
    origin = binding["canonical_function"]
    assert list(value.metadata["bindings"]).index(origin) < list(value.metadata["bindings"]).index(
        name
    )
    assert value.metadata["bindings"][origin]["tool"] == "http"
    function = value.metadata["tools"][0]["function"]
    Draft202012Validator(function["parameters"]).validate({"arguments": {"domain": domain}})
    decision = decode_calls(value.metadata, [call(name, {"arguments": {"domain": domain}})])
    assert decision["kind"] == "tool" and decision["tool"] == "http"
    assert decision["integration_id"] == "ha"
    assert decision["arguments"] == {
        "method": "GET",
        "path": "/api/states",
        "projection": {
            "items_path": "",
            "where_pointer": "/entity_id",
            "where_prefix": domain + ".",
            "where_equals": None,
            "fields": [],
            "limit": 100,
        },
    }
    normalized, effect = validate_tool(
        "home_assistant", rules, decision["tool"], decision["arguments"]
    )
    assert not effect and normalized["body"] is None and normalized["query"] == {}
    assert rules.http_methods == ["GET", "POST"]


@pytest.mark.parametrize("arguments", [{}, {"arguments": {}}, {"arguments": {"domain": None}}])
def test_missing_or_null_domain_uses_existing_frozen_context_narrowing(arguments):
    value, rules = build()
    decision = decode_calls(value.metadata, [call(facade(value), arguments)])
    assert decision["arguments"] == {"method": "GET", "path": "/api/states", "projection": None}
    narrowed = narrow_entity_read(
        "home_assistant",
        "ha",
        "http",
        decision["arguments"],
        {"requirements": [{"kind": "entity_states", "domain": "update", "integration_id": "ha"}]},
    )
    assert narrowed["projection"]["where_prefix"] == "update."
    assert not validate_tool("home_assistant", rules, "http", narrowed)[1]


@pytest.mark.parametrize(
    "options",
    [
        {"kind": "paperless"},
        {"enabled": False},
        {"methods": ["POST"]},
        {"prefixes": ["/api/config/"]},
        {"prefixes": ["/api/states/"]},
        {"missing_target": "other"},
        {"evidence": False},
        {"domain": ""},
        {"domain": "UPDATES"},
    ],
)
def test_facade_is_absent_without_current_ha_entity_need_and_scoped_state_read(options):
    value, _ = build(**options)
    assert not any(name.endswith("_ha_entities") for name in value.metadata["bindings"])


@pytest.mark.parametrize(
    "bad",
    [
        {"domain": "sensor"},
        {"domain": "UPDATE"},
        {"domain": "update.bad"},
        {"domain": ""},
        {"domain": False},
        {"domain": 0},
        {"domain": []},
        {"domain": "update", "path": "/api/config"},
        {"domain": "update", "method": "POST"},
        {"domain": "update", "integration_id": "other"},
        {"domain": "update", "query": {}},
    ],
)
def test_alias_rejects_malformed_domain_or_arbitrary_transport_parameters(bad):
    value, _ = build()
    with pytest.raises(NativeCallError):
        decode_calls(value.metadata, [call(facade(value), {"arguments": bad})])


def test_missing_domains_are_closed_and_alias_indices_follow_actual_tool_targets():
    value, _ = build(leading_disabled=True)
    assert facade(value) == "t0_ha_entities"
    binding = value.metadata["bindings"][facade(value)]
    assert binding["integration_id"] == "ha"
    domain_schema = value.metadata["tools"][0]["function"]["parameters"]["properties"]["arguments"][
        "properties"
    ]["domain"]
    assert domain_schema["anyOf"][0]["enum"] == ["update"]
    assert "disabled" not in {b.get("integration_id") for b in value.metadata["bindings"].values()}


def test_alias_validates_generated_arguments_against_original_http_schema():
    value, _ = build()
    metadata = deepcopy(value.metadata)
    name = facade(value)
    original_name = metadata["bindings"][name]["canonical_function"]
    original = next(
        row["function"] for row in metadata["tools"] if row["function"]["name"] == original_name
    )
    original["parameters"]["properties"]["arguments"]["properties"]["path"]["const"] = "/api/other"
    metadata["sha256"] = _digest(metadata)
    with pytest.raises(NativeCallError):
        decode_calls(metadata, [call(name, {"arguments": {"domain": "update"}})])


@pytest.mark.parametrize("change", ["hash", "target", "tool", "recursive"])
def test_alias_metadata_is_hashed_and_cannot_rebind_target_or_tool(change):
    value, _ = build()
    metadata = deepcopy(value.metadata)
    name = facade(value)
    if change == "hash":
        metadata["bindings"][name]["canonical_function"] = "unknown"
    else:
        if change == "target":
            metadata["bindings"][name]["integration_id"] = "other"
        elif change == "tool":
            metadata["bindings"][name]["tool"] = "shell"
        else:
            metadata["bindings"][name]["canonical_function"] = name
        metadata["sha256"] = _digest(metadata)
    with pytest.raises(NativeCallError):
        decode_calls(metadata, [call(name, {"arguments": {"domain": "update"}})])


def test_alias_decode_does_not_recursively_decode_or_dispatch_a_target(monkeypatch):
    import hub.agent_native as native
    import hub.agent_tools as tools

    value, _ = build()
    original, seen = native.decode_calls, []

    def decode(*args):
        seen.append(True)
        return original(*args)

    monkeypatch.setattr(native, "decode_calls", decode)
    monkeypatch.setattr(
        tools, "invoke", lambda *a, **kw: pytest.fail("No target dispatch in codec")
    )
    assert (
        decode(value.metadata, [call(facade(value), {"arguments": {"domain": "update"}})])["tool"]
        == "http"
    )
    assert seen == [True]


def test_existing_http_and_history_remain_canonical_not_replayed_as_facade():
    value, _ = build()
    name = facade(value)
    origin = value.metadata["bindings"][name]["canonical_function"]
    args = {"method": "GET", "path": "/api/states", "projection": None}
    assert decode_calls(value.metadata, [call(origin, {"arguments": args})])["arguments"] == args
    fitted = deepcopy(value.data)
    fitted["history"] = [
        {
            "sequence": 1,
            "kind": "read",
            "status": "succeeded",
            "document": {"integration_id": "ha", "tool": "http", "arguments": args},
            "result": {"http_status": 200, "body": []},
        }
    ]
    compiled, model_data = with_history(value, fitted)
    messages = native_messages(compiled.metadata)
    assert len(messages) == 2 and model_data["history"] == []
    assert messages[0]["tool_calls"][0]["function"]["name"] == origin
    assert len(compiled.metadata["bindings"]) == len(value.metadata["bindings"])
    assert value.metadata["sha256"] == _digest(value.metadata)


def test_history_reconstruction_ignores_aliases_even_after_sorted_json_round_trip():
    from dataclasses import replace

    value, _ = build()
    metadata = json.loads(json.dumps(value.metadata, sort_keys=True))
    name = facade(value)
    origin = metadata["bindings"][name]["canonical_function"]
    # Serialized metadata keys sort the semantic name before tN_http; ordering
    # must never turn an actual HTTP history entry into a new semantic call.
    assert list(metadata["bindings"]).index(name) < list(metadata["bindings"]).index(origin)
    restored = replace(value, metadata=metadata)
    data = deepcopy(value.data)
    data["history"] = [
        {
            "sequence": 1,
            "kind": "read",
            "status": "succeeded",
            "document": {
                "integration_id": "ha",
                "tool": "http",
                "arguments": {"method": "GET", "path": "/api/states", "projection": None},
            },
            "result": {"http_status": 200, "body": []},
        }
    ]
    compiled, model_data = with_history(restored, data)
    assert model_data["history"] == []
    assert native_messages(compiled.metadata)[0]["tool_calls"][0]["function"]["name"] == origin
