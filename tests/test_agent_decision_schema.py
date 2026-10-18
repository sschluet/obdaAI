"""Typed generation grammar is a constraint, never execution authority."""

import copy
import json

import pytest
from hub.agent_context import fit
from hub.agent_runtime import INSTRUCTION
from hub.agent_tools import SCHEMAS, Rules, decision_envelope_schema, decision_schema
from jsonschema import Draft202012Validator

TARGET = "00000000-0000-0000-0000-000000000001"
PROOF = {"path": "/api/status/", "expected": {"/http_status": 200}}
VALID = {
    "ssh.inspect": {},
    "mcp.catalog": {},
    "http": {
        "method": "GET",
        "path": "/api/tags/",
        "query": {"page": 1},
        "projection": {"items_path": "/results", "fields": ["/id", "/name"]},
    },
    "http.verify": {
        "method": "GET",
        "path": "/api/status/",
        "effect_step": 1,
        "expected": {"/http_status": 200},
    },
    "http.upload": {
        "path": "/api/documents/",
        "source_id": TARGET,
        "source_revision": 1,
        "source_sha256": "a" * 64,
        "verification": PROOF,
    },
    "ha.websocket": {"type": "backup/info", "parameters": {}},
    "mail.send": {"recipient": "owner@example.test", "subject": "Synthetic", "text": "Test"},
    "research": {"topic": "interfaces"},
    "shell": {"script": "printf test", "verification_script": "test 1 = 1"},
    "file.read": {"path": "/tmp/synthetic"},
    "mcp.call": {"name": "synthetic", "schema_sha256": "a" * 64, "arguments": {"id": 1}},
}


def decision(tool, arguments):
    return {
        "kind": "tool",
        "message": "Inspect the selected target",
        "integration_id": TARGET,
        "tool": tool,
        "arguments": arguments,
    }


@pytest.mark.parametrize("tool", sorted(SCHEMAS))
def test_each_tool_accepts_actual_valid_arguments_with_root_resolvable_refs(tool):
    schema = decision_schema([TARGET])
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(decision(tool, VALID[tool]))
    SCHEMAS[tool].model_validate(VALID[tool])


@pytest.mark.parametrize("tool", sorted(SCHEMAS))
def test_extra_argument_fields_are_forbidden(tool):
    assert not Draft202012Validator(decision_schema([TARGET])).is_valid(
        decision(tool, {**VALID[tool], "invented_argument": True})
    )


@pytest.mark.parametrize(
    ("tool", "field", "value"),
    [
        ("shell", "script", 42),
        ("file.read", "path", False),
        ("research", "topic", "invented"),
        ("mcp.call", "arguments", []),
        ("http", "query", {"page": []}),
        ("http", "projection", {"limit": "10"}),
        ("http.verify", "effect_step", 0),
        ("http.verify", "effect_step", "1"),
        ("http.verify", "expected", {}),
        ("http.verify", "expected", {"http_status": 200}),
        ("http.upload", "verification", {"path": "/api/", "expected": {"wrong": 200}}),
    ],
)
def test_wrong_types_bounds_and_pointer_keys_are_rejected(tool, field, value):
    assert not Draft202012Validator(decision_schema([TARGET])).is_valid(
        decision(tool, {**VALID[tool], field: value})
    )


@pytest.mark.parametrize("tool", ["http", "http.verify"])
def test_get_requires_explicit_method_and_forbids_effect_parameters(tool):
    validator = Draft202012Validator(decision_schema([TARGET]))
    for field, value in (("body", {}), ("verification", PROOF)):
        assert not validator.is_valid(decision(tool, {**VALID[tool], field: value}))
    missing = {key: value for key, value in VALID[tool].items() if key != "method"}
    assert not validator.is_valid(decision(tool, missing))
    validator.validate(decision(tool, {**VALID[tool], "body": None, "verification": None}))


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_http_writes_retain_typed_body_and_verification(method):
    validator = Draft202012Validator(decision_schema([TARGET]))
    arguments = {
        "method": method,
        "path": "/api/tags/",
        "body": {"name": "Synthetic"},
        "verification": PROOF,
    }
    validator.validate(decision("http", arguments))
    assert not validator.is_valid(
        decision("http.verify", {**VALID["http.verify"], "method": method})
    )


def test_tool_selection_is_exact_and_empty_allows_only_text():
    validator = Draft202012Validator(decision_schema([TARGET], ["file.read"]))
    validator.validate(decision("file.read", VALID["file.read"]))
    assert not validator.is_valid(decision("shell", VALID["shell"]))
    empty = Draft202012Validator(decision_schema([TARGET], []))
    for kind in ("ask", "finish"):
        empty.validate({"kind": kind, "message": "Synthetic"})
    assert not empty.is_valid(decision("file.read", VALID["file.read"]))
    assert not empty.is_valid({"kind": "finish", "message": "Synthetic", "arguments": {}})
    with pytest.raises(ValueError, match="Unknown"):
        decision_schema([TARGET], ["invented"])
    with pytest.raises(ValueError, match="selected targets"):
        decision_schema([], ["file.read"])


def test_schema_does_not_mutate_sources_or_grant_unselected_targets():
    before = copy.deepcopy(SCHEMAS["http"].model_json_schema())
    schema = decision_schema([TARGET], ["http"])
    validator = Draft202012Validator(schema)
    assert not validator.is_valid(
        {**decision("http", VALID["http"]), "integration_id": "different-target"}
    )
    assert SCHEMAS["http"].model_json_schema() == before


def test_compact_prompt_contract_fits_ha_budget_without_duplicating_full_grammar():
    names = ["http", "http.verify", "http.upload", "ha.websocket", "research"]
    envelope = decision_envelope_schema([TARGET], names)
    full = decision_schema([TARGET], names)
    assert len(json.dumps(envelope)) < 1600
    assert len(json.dumps(full)) > 5000
    for name in names:
        Draft202012Validator(envelope).validate(decision(name, VALID[name]))
    data = {
        "goal": "Inspect the current installation and verify the requested configuration.",
        "interfaces": [
            {
                "integration_id": TARGET,
                "kind": "home_assistant",
                "name": "Synthetic HA",
                "writes_enabled": True,
                "rules": Rules(
                    enabled=True,
                    autonomous=True,
                    http_prefixes=["/api/"],
                    ha_websocket_prefixes=["config/", "supervisor/"],
                    home_assistant_host=True,
                    production_ha_approved=True,
                ).model_dump(),
            }
        ],
        "tools": {name: SCHEMAS[name].model_json_schema() for name in names},
        "decision_schema": envelope,
        "private_context": [{"text": "Synthetic private context " * 1000}],
        "history": [
            {
                "kind": "read",
                "sequence": 1,
                "document": {"tool": "http"},
                "result": {
                    "body": {"states": [{"id": "synthetic"}] * 1000},
                    "http_status": 200,
                    "effect_verified": False,
                },
            }
        ],
    }
    fitted = fit(data, INSTRUCTION, 24000)
    assert fitted["tools"] == data["tools"]
    assert fitted["decision_schema"] == envelope
    assert len(INSTRUCTION) + len(json.dumps(fitted, ensure_ascii=False)) < 24000
    assert "$defs" not in fitted["decision_schema"]
    assert "Tool_http" in full["$defs"]


def test_compact_contract_preserves_tool_selection_and_old_snapshot_defaults():
    for schema_fn in (decision_envelope_schema, decision_schema):
        empty = Draft202012Validator(schema_fn([TARGET], []))
        empty.validate({"kind": "ask", "message": "Synthetic"})
        assert not empty.is_valid(decision("http", VALID["http"]))
        with pytest.raises(ValueError, match="Unknown"):
            schema_fn([TARGET], ["invented"])
    # Missing tool_names in older snapshots is intentionally represented by None.
    assert decision_schema([TARGET], None) == decision_schema([TARGET], list(SCHEMAS))
