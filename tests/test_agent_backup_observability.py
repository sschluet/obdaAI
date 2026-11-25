"""Configured backup proofs must be observable before any mutation is sent."""

from copy import deepcopy

import pytest
from hub.agent_path_grammar import ha_service_execution_path
from hub.agent_prerequisites import backup_observability, check
from hub.agent_tools import validate_tool
from test_agent_effect_prerequisites import RULE, rules, step

PATH = "/api/states/sensor.backup"
ARGS = {"method": "POST", "path": RULE["requires"]["path"], "verification": {
    "path": PATH, "query": {}, "expected": {"/body/state": "ready"},
}}


def read(body=None, **updates):
    row = step(1, "read", {"integration_id": "ha", "tool": "http", "arguments": {
        "method": "GET", "path": PATH, "query": {}, "projection": None,
    }}, {"http_status": 200, "body": {"state": "idle"} if body is None else body})
    for key, value in updates.items():
        setattr(row, key, value)
    return row


def issue(history, arguments=None, **updates):
    return backup_observability(history, "ha", rules(), "http", arguments or ARGS,
                                job_id="job", kind=updates.get("kind", "home_assistant"))


def test_exact_observed_differing_field_allows_backup_not_static_already_true():
    assert issue([read()]) is None
    assert issue([read({"state": "ready"})])["type"] == "backup_verification_already_true"
    assert issue([])["required_read"]["path"] == PATH
    with pytest.raises(PermissionError, match="Backup"):
        check([], "ha", rules(), "http", ARGS, job_id="job", kind="home_assistant")


@pytest.mark.parametrize("changes", [
    {"job_id": "foreign"}, {"sha256": "tampered"}, {"status": "failed"},
    {"result": '{"http_status":true,"body":{"state":"idle"}}'},
    {"result": '{"http_status":200,"body":{},"projection_error":"bad"}'},
])
def test_foreign_tampered_failed_receipts_never_authorize_backup(changes):
    assert issue([read(**changes)]) is not None


def test_latest_failed_or_intervening_target_effect_invalidates_read():
    failed = read(status="failed", sequence=2)
    assert issue([read(), failed]) is not None
    effect = step(2, "effect", {"integration_id": "ha"}, {})
    assert issue([read(), effect]) is not None
    effect.document = '{"integration_id":"other"}'
    assert issue([read(), effect]) is None


@pytest.mark.parametrize("body,wanted,allowed", [
    ({}, None, False), ({"state": None}, "ready", False),
    ({"state": False}, 0, False), ({"state": 0}, False, False),
    ({"state": False}, True, True), ({"state": 0}, 1, True),
    ({"state": None}, None, False),
    ({"state": [0]}, [False], False),
    ({"state": {"x": 0}}, {"x": False}, False),
    ({"state": [1]}, [1.0], False),
    ({"state": {"x": 1}}, {"x": 1.0}, False),
])
def test_presence_and_json_type_are_exact(body, wanted, allowed):
    args = deepcopy(ARGS)
    args["verification"]["expected"] = {"/body/state": wanted}
    assert (issue([read(body)], args) is None) is allowed


def test_other_operations_and_unconfigured_backups_keep_existing_contract():
    args = {**ARGS, "path": RULE["operation"]["path"]}
    assert issue([], args) is None
    assert issue([], kind="paperless") is None
    assert backup_observability([], "ha", rules().model_copy(update={
        "effect_prerequisites": []}), "http", ARGS, job_id="job", kind="home_assistant") is None


@pytest.mark.parametrize("path", [
    "/api/services/backup/create", "/API/SERVICES/backup/create/",
    "/api/services/update/install",
])
def test_service_execution_is_not_a_verification_get(path):
    assert ha_service_execution_path(path)
    with pytest.raises((ValueError, PermissionError)):
        validate_tool("home_assistant", rules(), "http.verify", {
            "path": path, "effect_step": 1, "expected": {"/body/state": "ready"},
        })
    args = deepcopy(ARGS)
    args["verification"]["path"] = path
    with pytest.raises((ValueError, PermissionError)):
        validate_tool("home_assistant", rules(), "http", args)


@pytest.mark.parametrize("path", [
    "/api/services", "/api/services/", "/api/services/status",
    "/api/services/a/b/status", "/api/states/sensor.backup", "/api/custom/future",
])
def test_catalog_and_custom_status_routes_not_globally_disallowed(path):
    assert not ha_service_execution_path(path)
    validate_tool("home_assistant", rules(), "http.verify", {
        "path": path, "effect_step": 1, "expected": {"/body/state": "ready"},
    })


def test_actual_native_sse_keeps_canonical_service_verification_guard(monkeypatch, tmp_path):
    import json

    import httpx
    from test_agent_native_active_http import compiled
    from test_agent_native_transport import adapter, collect, event, fragment

    prepared, permitted = compiled()
    args = deepcopy(ARGS)
    args["verification"]["path"] = RULE["requires"]["path"]
    response = httpx.Response(200, text=event(fragment(
        "t0_http_change", json.dumps({"arguments": args}),
    )) + "data: [DONE]\n\n")
    provider, _, requests = adapter(monkeypatch, tmp_path, response)
    provider.local_native_plan = prepared.metadata
    decision = json.loads(collect(provider)[0])
    assert decision["kind"] == "tool"
    # Native syntax is not authority: the same production canonical gate executes
    # before preparing/dispatching the effect and rejects the invented GET.
    with pytest.raises(ValueError, match="POST-only"):
        validate_tool("home_assistant", permitted, decision["tool"], decision["arguments"])
    assert len(requests) == 1  # model transport only, no target dispatcher used
    tools = json.loads(requests[0].content)["tools"]
    assert "POST-only /api/services/domain/service" in json.dumps(tools)
