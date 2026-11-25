"""Synthetic administration context keeps durable effect identity and uncertainty."""

import copy
import hashlib
import json

import pytest
from hub.agent_context import AgentContextLimitError, fit


def digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def effect(sequence, **changes):
    row = {"sequence": sequence, "kind": "effect", "status": "succeeded",
           "document": {"tool": "http", "integration_id": "synthetic-target",
                        "target": {"profile_revision": 7, "config_sha256": "a" * 64},
                        "arguments": {"method": "POST", "path": "/api/services/update/install",
                                      "body": {"entity_id": "update.synthetic_" + str(sequence)},
                                      "verification": {"path": "/api/states/update.synthetic",
                                                       "expected": {"/body/state": "off"}}}},
           "result": {"http_status": 200, "effect_verified": True,
                      "verification_passed": True, "acknowledged": False,
                      "reconciled_after_uncertain": True, "causation_verified": False,
                      "verification": {"effect_verified": True, "exit_code": 0},
                      "body": {"synthetic": "payload " * 2000}}}
    row.update(changes)
    return row


def data(rows):
    return {"goal": "Install all authorized synthetic updates", "interfaces": [{"id": "bound"}],
            "tools": {"http": {"authority": "unchanged"}}, "history": rows,
            "private_context": []}


def test_twenty_effects_have_individual_provenance_and_no_authority_change():
    original = data([effect(i) for i in range(1, 21)])
    saved = copy.deepcopy(original)
    fitted = fit(original, "Trusted policy", 25000)
    assert len(fitted["effect_ledger"]) == 19
    assert fitted["history"][-1]["sequence"] == 20
    for ledger, row in zip(fitted["effect_ledger"], original["history"], strict=False):
        assert ledger["sequence"] == row["sequence"]
        assert ledger["document"] == row["document"]
        assert ledger["document_sha256"] == digest(row["document"])
        assert ledger["arguments_sha256"] == digest(row["document"]["arguments"])
        assert ledger["result_sha256"] == digest(row["result"])
        for key in row["result"]:
            if key != "body":
                assert ledger["result"][key] == row["result"][key]
        assert ledger["result"]["body"]["content_omitted"] is True
        assert ledger["model_view_only"] is True
    assert fitted["tools"] == original["tools"]
    assert fitted["interfaces"] == original["interfaces"]
    assert original == saved


@pytest.mark.parametrize("status", ["dispatching", "verifying", "uncertain", "failed", "succeeded"])
def test_unverified_effect_preserved_exactly_and_never_inferred_from_http_success(status):
    unresolved = effect(1, status=status, result={"http_status": 200, "effect_verified": False,
                                                "error": "synthetic reason" * 100})
    fitted = fit(data([unresolved, effect(2)]), "Policy", 10000)
    assert fitted["history"][0] == unresolved
    assert not fitted.get("effect_ledger")


def test_oversized_uncertain_payload_fails_closed_without_losing_proof():
    unresolved = effect(1, status="uncertain", result={
        "effect_verified": False, "unresolved_evidence": "x" * 30000,
    })
    original = data([unresolved])
    with pytest.raises(AgentContextLimitError):
        fit(original, "Policy", 10000)
    assert original["history"][0] == unresolved


def test_verification_keeps_effect_link_expected_values_and_negative_flags():
    verified = effect(2, kind="verification")
    verified["document"]["arguments"] = {"effect_step": 1, "expected": {"/body/state": "off"}}
    verified["result"]["delivery_verified"] = False
    fitted = fit(data([effect(1), verified, effect(3)]), "Policy", 7000)
    item = fitted["effect_ledger"][1]
    assert item["document"]["arguments"] == verified["document"]["arguments"]
    assert item["result"]["delivery_verified"] is False
    assert item["result"]["causation_verified"] is False


def test_uncertain_shell_payload_is_omitted_explicitly_but_proof_and_script_hash_survive():
    row = effect(1, status="uncertain")
    row["document"]["arguments"] = {
        "script": "SYNTHETIC SCRIPT " * 2000,
        "verification_script": "SYNTHETIC VERIFY " * 2000,
        "effect_step": 7,
    }
    row["result"] = {"effect_verified": False, "reconciled_after_uncertain": False,
                     "verification": {"exit_code": 1, "stdout": "x" * 30000},
                     "failure_phase": "verification", "stdout": "x" * 30000}
    fitted = fit(data([row]), "Policy", 10000)
    actual = fitted["history"][0]
    assert actual["status"] == "uncertain"
    assert not fitted.get("effect_ledger")
    assert actual["document"]["arguments"]["effect_step"] == 7
    for field in ("script", "verification_script"):
        assert actual["document"]["arguments"][field] == {
            "content_omitted": True, "full_sha256": digest(row["document"]["arguments"][field]),
        }
    assert actual["result"]["effect_verified"] is False
    assert actual["result"]["reconciled_after_uncertain"] is False
    assert actual["result"]["verification"]["exit_code"] == 1
    assert actual["result"]["failure_phase"] == "verification"


def test_static_authority_never_shrinks_to_make_an_impossible_budget_pass():
    original = data([effect(1)])
    original["tools"] = {"must_remain_exact": "x" * 15000}
    saved = copy.deepcopy(original)
    with pytest.raises(AgentContextLimitError):
        fit(original, "Policy", 10000)
    assert original == saved


def test_large_ha_config_keeps_late_scalar_facts_not_a_fabricated_complete_body():
    from hub.agent_context import _observation

    body = {"components": ["synthetic_component_" + str(i) for i in range(2000)],
            "version": "2026.11.4", "state": "RUNNING", "installation_type": "Home Assistant OS",
            "safe_mode": False, "zero": 0, "optional": None}
    entry = {"sequence": 3, "kind": "read", "status": "succeeded",
             "document": {"tool": "http", "arguments": {"method": "GET", "path": "/api/config"}},
             "result": {"http_status": 200, "body": body}}
    saved = copy.deepcopy(entry)
    observation = _observation(entry, metadata_limit=1000)
    view = observation["summary"]["semantic_view"]
    assert view["object_path"] == "/body" and view["model_view_only"] is True
    assert view["fields"] == {key: value for key, value in body.items() if key != "components"}
    assert view["observed_field_count"] == 7 and view["omitted_field_count"] == 1
    assert view["containers_omitted"] == 1
    assert "components" not in view["fields"]
    assert "truncated" not in observation["result"]
    assert observation["result"]["body"] == view["fields"]
    assert observation["result"]["full_sha256"] == digest(entry["result"])
    assert observation["step_status"] == "succeeded" and observation["model_view_only"] is True
    assert observation["summary"]["http_status"] == 200
    assert entry == saved


def test_object_view_utf8_budget_and_order_do_not_lose_false_zero_or_null():
    from hub.agent_context import _semantic_view

    body = {"components": ["漢" * 1000], "too_large": "漢" * 1000,
            "version": "2026.11", "enabled": False, "count": 0, "empty": None,
            "label": "Größe 漢字"}
    view = _semantic_view({"body": body}, 500)
    assert view is not None and len(json.dumps(view, ensure_ascii=False).encode()) <= 500
    assert view["fields"] == {key: body[key] for key in
                              ("version", "enabled", "count", "empty", "label")}
    assert view["omitted_field_count"] == 2 and view["containers_omitted"] == 1
    assert _semantic_view({"body": dict(reversed(list(body.items())))}, 500) == view
    assert _semantic_view({"body": body}, 5) is None


def test_object_view_does_not_invent_missing_known_fields_or_change_failed_status():
    from hub.agent_context import _observation

    observation = _observation({"sequence": 4, "status": "failed",
                                "result": {"http_status": 403, "body": {"message": "Denied"}}})
    fields = observation["summary"]["semantic_view"]["fields"]
    assert fields == {"message": "Denied"}
    assert "version" not in fields and "state" not in fields
    assert observation["step_status"] == "failed"
    assert observation["summary"]["http_status"] == 403


def test_update_entity_view_retains_observed_versions_and_flags_without_inference():
    from hub.agent_context import _semantic_view

    attributes = {"installed_version": "1.2", "latest_version": "1.3", "in_progress": False,
                  "supported_features": 0, "friendly_name": "Synthetic update"}
    rows = [{"entity_id": "update.synthetic", "state": "on", "attributes": attributes},
            {"entity_id": "update.other", "state": "unknown", "attributes": {
                "installed_version": None, "latest_version": "2", "in_progress": 0,
                "supported_features": 1}}]
    saved = copy.deepcopy(rows)
    view = _semantic_view({"body": rows}, 800)
    assert view["items"][0]["attributes"] == attributes
    assert view["items"][1]["attributes"] == rows[1]["attributes"]
    assert view["items"][0]["state"] == "on"
    assert "update_available" not in json.dumps(view)
    assert len(json.dumps(view, ensure_ascii=False).encode()) <= 800
    assert rows == saved


def test_projected_update_pointers_retain_actual_null_false_zero_and_version_difference():
    from hub.agent_context import _semantic_view

    row = {"/entity_id": "update.synthetic", "/state": "off",
           "/attributes/installed_version": "2026.10", "/attributes/latest_version": "2026.11",
           "/attributes/in_progress": False, "/attributes/supported_features": 0}
    missing = {"/entity_id": "update.missing", "/state": "unavailable",
               "/attributes/installed_version": None}
    source = {"body": {"items": [row, missing], "matched": 2, "returned": 2}}
    saved = copy.deepcopy(source)
    view = _semantic_view(source, 800)
    assert view["items"] == [row, missing]
    assert "/attributes/latest_version" not in view["items"][1]
    assert view["source_counts"] == {"matched": 2, "returned": 2}
    assert len(json.dumps(view, ensure_ascii=False).encode()) <= 800
    assert source == saved


def test_large_successful_http_object_uses_same_typed_result_in_history_and_latest():
    components = ["SYNTHETIC_COMPONENT_PAYLOAD_" + str(i) for i in range(2000)]
    entry = {"sequence": 3, "kind": "read", "status": "succeeded",
             "document": {"tool": "http", "arguments": {"method": "GET", "path": "/api/config"}},
             "result": {"http_status": 200, "effect_verified": False, "body": {
                 "components": components, "version": "2026.11.4", "state": "RUNNING",
                 "safe_mode": False, "zero": 0, "optional": None},
                 "transport_flag": False}}
    original = data([entry])
    saved = copy.deepcopy(original)
    fitted = fit(original, "Policy", 8000)
    historical = fitted["history"][0]["result"]
    latest = fitted["latest_observation"]["result"]
    for result in (historical, latest):
        assert result["http_status"] == 200 and result["effect_verified"] is False
        assert result["transport_flag"] is False and result["model_view_only"] is True
        assert result["full_sha256"] == digest(entry["result"])
        assert result["body"] == {
            "version": "2026.11.4", "state": "RUNNING", "safe_mode": False,
            "zero": 0, "optional": None}
        assert result["body_view"]["omitted_field_count"] == 1
        assert "excerpt" not in result and "truncated" not in result
    assert "SYNTHETIC_COMPONENT_PAYLOAD_" not in json.dumps(fitted)
    assert fitted["latest_observation"]["step_status"] == "succeeded"
    assert original == saved


@pytest.mark.parametrize(
    "kind,status,http_status,tool,method",
    [
        ("effect", "succeeded", 200, "http", "GET"),
        ("verification", "succeeded", 200, "http.verify", "GET"),
        ("read", "failed", 403, "http", "GET"),
        ("read", "succeeded", 200, "http", "POST"),
    ],
)
def test_typed_http_object_replacement_never_applies_to_effects_or_failed_reads(
    kind, status, http_status, tool, method,
):
    from hub.agent_context import _http_object_result

    entry = {"kind": kind, "status": status,
             "document": {"tool": tool, "arguments": {"method": method}},
             "result": {"http_status": http_status, "body": {"components": ["x" * 8000]}}}
    assert _http_object_result(entry, 500) is None
    entry["kind"], entry["status"] = "read", "succeeded"
    entry["document"] = {"tool": "http", "arguments": {"method": "GET"}}
    entry["result"]["projection_error"] = "invalid selection"
    result = _http_object_result(entry, 500)
    if http_status == 200:
        assert result is not None and result["projection_error"] == "invalid selection"
    else:
        assert result is None
