"""Typed generation grammar is a constraint, never execution authority."""

import copy
import json

import pytest
from hub.agent_context import fit
from hub.agent_runtime import INSTRUCTION
from hub.agent_tools import (
    SCHEMAS,
    Rules,
    decision_envelope_schema,
    decision_schema,
    ready_read_schema,
)
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
    "gmail.read": {"operation": "labels"},
    "paperless.read": {"operation": "search", "query": "Synthetic invoice"},
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


@pytest.mark.parametrize(
    "path",
    [
        "/api/tags/?name=Synthetic",
        "/api/tags/%20",
        "/api/tags/has space",
        "/api/#fragment",
        "https://example.test/api/",
        "api/tags/",
        "/api/ümlaut",
        "/api/\\escape",
    ],
)
def test_api_path_grammar_rejects_query_urls_and_encoded_or_nonplain_paths(path):
    validator = Draft202012Validator(decision_schema([TARGET]))
    for tool in ("http", "http.verify", "http.upload"):
        assert not validator.is_valid(decision(tool, {**VALID[tool], "path": path}))
    write = {"method": "POST", "path": path, "body": {"name": "Synthetic"}}
    assert not validator.is_valid(decision("http", write))
    for tool, arguments in (
        ("http", {"method": "POST", "path": "/api/tags/"}),
        ("http.upload", VALID["http.upload"]),
        ("ha.websocket", VALID["ha.websocket"]),
    ):
        assert not validator.is_valid(
            decision(tool, {**arguments, "verification": {**PROOF, "path": path}})
        )


@pytest.mark.parametrize("path", ["/", "/api/tags/", "/api/config/a_b~c-d.1/"])
def test_plain_api_paths_still_validate_for_reads_writes_uploads_and_prebound_checks(path):
    validator = Draft202012Validator(decision_schema([TARGET]))
    for tool in ("http", "http.verify", "http.upload"):
        arguments = {**VALID[tool], "path": path}
        validator.validate(decision(tool, arguments))
        SCHEMAS[tool].model_validate(arguments)
    arguments = {
        "method": "PATCH",
        "path": path,
        "body": {"name": "Synthetic"},
        "verification": {**PROOF, "path": path},
    }
    validator.validate(decision("http", arguments))
    SCHEMAS["http"].model_validate(arguments)


@pytest.mark.parametrize("path", ["//api/tags/", "/api/../tags/", "/api/./tags/"])
def test_final_plain_path_validation_remains_stricter_than_generation_subset(path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SCHEMAS["http"].model_validate({"method": "GET", "path": path})


HA_TARGET = "00000000-0000-0000-0000-000000000002"


def bound_interfaces():
    return [
        {
            "integration_id": TARGET,
            "kind": "ssh",
            "rules": Rules(
                enabled=True, shell=True, http_prefixes=["/api/"], http_methods=["GET", "POST"]
            ).model_dump(),
        },
        {
            "integration_id": HA_TARGET,
            "kind": "home_assistant",
            "rules": Rules(
                enabled=True,
                shell=True,
                http_prefixes=["/api/"],
                http_methods=["GET", "POST"],
                file_upload=True,
                ha_websocket_prefixes=["config/", "backup/info", "supervisor/api"],
            ).model_dump(),
        },
    ]


def test_bound_interfaces_enforce_kind_tool_mapping_and_ha_command_scopes():
    validator = Draft202012Validator(
        decision_schema([TARGET, HA_TARGET], interfaces=bound_interfaces())
    )
    validator.validate(decision("shell", VALID["shell"]))
    assert not validator.is_valid(
        {**decision("shell", VALID["shell"]), "integration_id": HA_TARGET}
    )
    assert not validator.is_valid(decision("http", VALID["http"]))
    for command in ("config/automation/list", "backup/info", "supervisor/api"):
        validator.validate(
            {**decision("ha.websocket", {"type": command}), "integration_id": HA_TARGET}
        )
    for command in (
        "automation",
        "configuration/list",
        "backup/info_extra",
        "supervisor/api/extra",
    ):
        assert not validator.is_valid(
            {**decision("ha.websocket", {"type": command}), "integration_id": HA_TARGET}
        )
    assert not validator.is_valid(decision("ha.websocket", {"type": "config/automation/list"}))


def test_bound_http_methods_prefixes_and_prebound_scopes_are_enforced():
    validator = Draft202012Validator(
        decision_schema([TARGET, HA_TARGET], interfaces=bound_interfaces())
    )

    def http(arguments):
        return {**decision("http", arguments), "integration_id": HA_TARGET}

    validator.validate(http({"method": "GET", "path": "/api/tags/"}))
    validator.validate(http({"method": "POST", "path": "/api/tags/", "verification": PROOF}))
    assert not validator.is_valid(http({"method": "DELETE", "path": "/api/tags/"}))
    assert not validator.is_valid(http({"method": "GET", "path": "/api-other/"}))
    assert not validator.is_valid(
        http(
            {
                "method": "POST",
                "path": "/api/tags/",
                "verification": {**PROOF, "path": "/elsewhere/"},
            }
        )
    )
    upload = {**VALID["http.upload"], "path": "/elsewhere/"}
    assert not validator.is_valid({**decision("http.upload", upload), "integration_id": HA_TARGET})


@pytest.mark.parametrize(
    "interfaces",
    [
        [],
        [{"integration_id": TARGET, "kind": "invented", "rules": {}}],
        [{"integration_id": TARGET, "kind": "ssh"}],
        [{"integration_id": "unselected", "kind": "ssh", "rules": {}}],
        [None],
        bound_interfaces() + bound_interfaces(),
    ],
)
def test_invalid_missing_unknown_or_duplicate_interfaces_fail_closed(interfaces):
    with pytest.raises(ValueError):
        decision_schema([TARGET, HA_TARGET], interfaces=interfaces)


def test_disabled_interfaces_offer_no_tools_and_legacy_none_stays_compatible():
    schema = decision_schema(
        [TARGET],
        interfaces=[{"integration_id": TARGET, "kind": "ssh", "rules": Rules().model_dump()}],
    )
    validator = Draft202012Validator(schema)
    validator.validate({"kind": "finish", "message": "No enabled tools"})
    assert not validator.is_valid(decision("ssh.inspect", {}))
    assert decision_schema([TARGET]) == decision_schema([TARGET], interfaces=None)


def test_smtp_and_mcp_cannot_cross_interfaces_and_recipient_scope_is_exact():
    interfaces = [
        {
            "integration_id": TARGET,
            "kind": "smtp",
            "rules": Rules(enabled=True, mail_recipients=["owner@example.test"]).model_dump(),
        },
        {
            "integration_id": HA_TARGET,
            "kind": "mcp",
            "rules": Rules(enabled=True, mcp=True).model_dump(),
        },
    ]
    schema = decision_schema([TARGET, HA_TARGET], interfaces=interfaces)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(decision("mail.send", VALID["mail.send"]))
    assert not validator.is_valid(
        decision("mail.send", {**VALID["mail.send"], "recipient": "other@example.test"})
    )
    assert not validator.is_valid(decision("mcp.call", VALID["mcp.call"]))
    validator.validate({**decision("mcp.call", VALID["mcp.call"]), "integration_id": HA_TARGET})


def test_scoped_ha_type_keeps_original_maximum_length():
    validator = Draft202012Validator(
        decision_schema([TARGET, HA_TARGET], interfaces=bound_interfaces())
    )
    allowed = "config/" + "a" * (151 - len("config/"))
    validator.validate({**decision("ha.websocket", {"type": allowed}), "integration_id": HA_TARGET})
    assert not validator.is_valid(
        {**decision("ha.websocket", {"type": allowed + "a"}), "integration_id": HA_TARGET}
    )


@pytest.mark.parametrize("schema_factory", [decision_envelope_schema, decision_schema])
def test_finish_requires_observed_evidence_but_questions_and_tools_stay_valid(schema_factory):
    schema = schema_factory([TARGET], ["paperless.read"], allow_finish=False)
    validator = Draft202012Validator(schema)
    assert not validator.is_valid({"kind": "finish", "message": "Invented answer"})
    assert validator.is_valid({"kind": "ask", "message": "Which actual missing account?"})
    assert validator.is_valid(decision("paperless.read", VALID["paperless.read"]))
    allowed = schema_factory([TARGET], ["paperless.read"], allow_finish=True)
    assert Draft202012Validator(allowed).is_valid({"kind": "finish", "message": "Observed"})


def test_evidence_gate_keeps_actual_interface_rules():
    rules = Rules(enabled=True, http_prefixes=["/api/"], http_methods=["GET"])
    schema = decision_schema(
        [TARGET],
        ["paperless.read", "shell", "http"],
        [{"integration_id": TARGET, "kind": "paperless", "rules": rules.model_dump()}],
        allow_finish=False,
    )
    validator = Draft202012Validator(schema)
    assert validator.is_valid(decision("paperless.read", VALID["paperless.read"]))
    assert not validator.is_valid(decision("shell", VALID["shell"]))
    assert not validator.is_valid(
        decision("http", {"method": "DELETE", "path": "/api/documents/7/"})
    )


@pytest.mark.parametrize("schema_factory", [decision_envelope_schema, decision_schema])
@pytest.mark.parametrize("queried", [False, True])
def test_private_read_grammar_never_asks_and_can_stop_without_inventing_parameters(
    schema_factory, queried
):
    schema = schema_factory(
        [TARGET],
        ["paperless.read"],
        allow_finish=queried,
        allow_ask=False,
        allow_stop=True,
    )
    validator = Draft202012Validator(schema)
    assert not validator.is_valid({"kind": "ask", "message": "Confirm the authorized read?"})
    assert validator.is_valid({"kind": "stop", "message": "Required identity is not available."})
    assert validator.is_valid(decision("paperless.read", VALID["paperless.read"]))
    assert validator.is_valid({"kind": "finish", "message": "Observed with limits"}) is queried


@pytest.mark.parametrize("schema_factory", [decision_envelope_schema, decision_schema])
def test_ordinary_administration_keeps_questions_and_does_not_offer_private_stop(schema_factory):
    validator = Draft202012Validator(schema_factory([TARGET], ["http"]))
    assert validator.is_valid({"kind": "ask", "message": "Which actual administrative target?"})
    assert not validator.is_valid({"kind": "stop", "message": "Private terminal"})


def test_concrete_read_grammar_accepts_only_current_source_bound_arguments():
    rules = Rules(enabled=True, mcp_read_tools={"read_email": "a" * 64})
    candidate = decision("mcp.call", {
        "name": "read_email", "schema_sha256": "a" * 64,
        "arguments": {"uid": 7, "folder": "INBOX"},
    })
    interfaces = [{"integration_id": TARGET, "kind": "mcp", "rules": rules.model_dump()}]
    schema = ready_read_schema([candidate], interfaces)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(candidate)
    for mutation in (
        {"kind": "stop", "message": "Select messages again"},
        decision("mcp.call", {**candidate["arguments"], "name": "get_status"}),
        decision("mcp.call", {**candidate["arguments"], "arguments": {
            "uid": 999, "folder": "INBOX",
        }}),
        decision("mcp.call", {**candidate["arguments"], "arguments": {
            "uid": 7, "folder": "other",
        }}),
    ):
        assert not validator.is_valid(mutation)
    revoked = [{**interfaces[0], "rules": Rules(enabled=False).model_dump()}]
    with pytest.raises(PermissionError):
        ready_read_schema([candidate], revoked)
