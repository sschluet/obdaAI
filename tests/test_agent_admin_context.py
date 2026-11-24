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
