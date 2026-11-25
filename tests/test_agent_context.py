"""Synthetic evidence fitting: preserve facts behind large response prefixes."""

import copy
import hashlib
import json

import pytest
from hub.agent_context import fit


def payload(result):
    return {
        "goal": "Inspect only the approved target",
        "interfaces": [{"id": "approved-only", "policy_revision": 3}],
        "tools": {"http": {"methods": ["GET"]}},
        "private_context": [{"text": "private" * 10000}],
        "history": [
            {"kind": "read", "sequence": 1, "document": {}, "result": {"old": "x" * 20000}},
            {"kind": "read", "sequence": 2, "document": {"tool": "http"}, "result": result},
        ],
    }


def test_latest_http_observation_preserves_late_structure_and_projection_error():
    response = {
        "body": {
            "all": list(range(1000)),
            "next": "https://example.test/" + "p" * 3000,
            "results": [{"id": 12, "name": "Synthetic tag", "document_count": 0}],
        },
        "effect_verified": False,
        "http_status": 200,
        "projection_error": "Selection does not match response structure",
    }
    original = payload(response)
    saved = copy.deepcopy(original)
    fitted = fit(original, "Fixed instruction", 8000)
    observation = fitted["latest_observation"]
    summary = observation["summary"]
    assert summary["http_status"] == 200
    assert summary["effect_verified"] is False
    assert summary["projection_error"] == response["projection_error"]
    shape = summary["body_shape"]
    assert "results" in shape["keys"]
    fields = {field["key"]: field["shape"] for field in shape["fields"]}
    assert fields["all"]["length"] == 1000
    assert fields["all"]["sample_item_types"] == ["number"]
    assert fields["results"]["sample_item_keys"] == ["id", "name", "document_count"]
    assert "id" not in summary
    assert observation["result"]["truncated"] is True
    encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    assert observation["full_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    assert observation["result"]["full_sha256"] == observation["full_sha256"]
    assert original == saved
    for key in ("goal", "interfaces", "tools"):
        assert fitted[key] == original[key]
    assert len("Fixed instruction") + len(json.dumps(fitted, ensure_ascii=False)) < 8000


@pytest.mark.parametrize("passed", [True, False])
def test_verification_status_survives_large_response(passed):
    fitted = fit(
        payload(
            {
                "body": {"text": "x" * 50000},
                "http_status": 200,
                "verification_passed": passed,
                "effect_verified": passed,
            }
        ),
        "",
        7000,
    )
    summary = fitted["latest_observation"]["summary"]
    assert summary["verification_passed"] is passed
    assert summary["effect_verified"] is passed


def test_latest_shell_status_survives_stdout_and_later_human_input():
    original = payload(
        {
            "stdout": "x" * 100000,
            "stderr": "",
            "exit_code": 0,
            "effect_verified": False,
            "verification": {"exit_code": 1, "stdout": "y" * 50000},
        }
    )
    original["history"][-1]["document"] = {"tool": "shell"}
    original["history"][-1]["kind"] = "effect"
    feedback = {
        "kind": "input",
        "sequence": 3,
        "document": {"message": "Please inspect. " * 150 + "Important final correction."},
        "result": {},
    }
    original["history"].append(feedback)
    fitted = fit(original, "", 10000)
    observation = fitted["latest_observation"]
    assert observation["sequence"] == 2
    assert observation["summary"]["exit_code"] == 0
    assert observation["summary"]["effect_verified"] is False
    assert observation["summary"]["verification"]["exit_code"] == 1
    assert observation["result"]["truncated"] is True
    assert fitted["latest_input"] == feedback
    assert fitted["latest_input"]["document"]["message"].endswith("Important final correction.")
    assert len(json.dumps(fitted, ensure_ascii=False)) < 10000


def test_impossible_budget_fails_closed_without_modifying_authority_or_input():
    original = payload({"http_status": 200})
    original["history"].append(
        {"kind": "input", "document": {"message": "x" * 10000}, "result": {}}
    )
    saved = copy.deepcopy(original)
    with pytest.raises(ValueError, match="context limit"):
        fit(original, "Fixed instruction", 5000)
    assert original == saved
    with pytest.raises(ValueError, match="context limit"):
        fit({"goal": "x" * 10000}, "", 5000)


def test_byte_budget_bounds_multibyte_evidence_without_clipping_authority():
    original = payload({"content": "Nachricht ÄÖÜ漢字" * 1500})
    saved = copy.deepcopy(original)
    fitted = fit(original, "Fixed instruction", 24000, max_bytes=7000)
    assert len(json.dumps(fitted, ensure_ascii=False, separators=(",", ":")).encode()) <= 7000
    assert fitted["interfaces"] == original["interfaces"]
    assert fitted["latest_observation"]["result"]["truncated"]
    assert original == saved
    with pytest.raises(ValueError, match="context limit"):
        fit({"goal": "漢" * 3000}, "", 24000, max_bytes=7000)


def test_observed_mail_progress_remains_structured_when_history_is_clipped():
    original = payload({"content": "Synthetic folder metadata " * 3000})
    original["mail_read_progress"] = {
        "folder_choices": [
            {
                "integration_id": "approved-only",
                "name": "INBOX",
                "flags": ["\\Inbox"],
                "selectable": True,
            }
        ],
        "next_action": "query_messages",
    }
    fitted = fit(original, "Local only", 24000, max_bytes=5000)
    assert fitted["history"][-1]["result"]["truncated"]
    assert fitted["mail_read_progress"] == original["mail_read_progress"]


def test_shapes_bound_keys_names_depth_and_sample_arrays():
    body = {
        str(i) + "k" * 100: [{"field" + str(j): {"deep": "x" * 10} for j in range(100)}] * 3
        for i in range(100)
    }
    body["results"] = [{"id": 1}]
    fitted = fit(payload({"body": body, "http_status": 200}), "", 24000)
    shape = fitted["latest_observation"]["summary"]["body_shape"]
    assert len(shape["keys"]) <= 12
    assert shape["keys_omitted"] == 101 - len(shape["keys"])
    assert shape["key_names_truncated"] is True
    assert "results" in shape["keys"]
    for field in shape["fields"]:
        assert len(field["key"]) <= 48
        assert field["key_truncated"] is (field["key"] != "results")
        assert field["shape"]["sampled_items"] <= 3
        assert len(field["shape"]["sample_item_keys"]) <= 12
    assert len(json.dumps(fitted["latest_observation"]["summary"], ensure_ascii=False)) <= 2500
    assert len(json.dumps(fitted, ensure_ascii=False)) < 24000


@pytest.mark.parametrize("kind", ["verification", "research"])
def test_verification_or_research_entry_is_latest_observation(kind):
    original = payload({"http_status": 200})
    original["history"].append(
        {
            "kind": kind,
            "sequence": 3,
            "document": {},
            "result": {"verification_passed": False},
        }
    )
    fitted = fit(original, "", 6000)
    assert fitted["latest_observation"]["sequence"] == 3
    assert fitted["latest_observation"]["summary"]["verification_passed"] is False


def test_large_inventory_keeps_typed_values_and_observed_counts_without_false_completeness():
    rows = [{"entity_id": f"sensor.fixture_{i}", "state": "17",
             "attributes": {"friendly_name": "Synthetic sensor", "large": "x" * 10000}}
            for i in range(200)]
    original = payload({"http_status": 200, "body": rows})
    fitted = fit(original, "Read data only; truncated samples are incomplete", 12000)
    typed = fitted["latest_observation"]["summary"]["semantic_view"]
    assert typed["observed_count"] == 200
    assert typed["observed_domain_counts"] == {"sensor": 200}
    assert typed["truncated"] is True and 0 < typed["returned"] < 200
    assert typed["items"][0]["entity_id"] == "sensor.fixture_0"
    assert typed["items"][0]["state"] == "17"
    assert "large" not in typed["items"][0]["attributes"]
    assert original["history"][-1]["result"]["body"] == rows


def terminal_effect(sequence=1):
    return {"sequence": sequence, "kind": "effect", "status": "succeeded", "approved": False,
        "document": {"tool": "http", "integration_id": "synthetic-target", "kind": "tool",
            "message": "Synthetic repetitive model display prose " * 8,
            "target": {"name": "Synthetic display name " * 5, "url": "https://synthetic.invalid",
                       "port": None, "username": None, "kind": "home_assistant",
                       "profile_revision": 2, "config_sha256": "a" * 64,
                       "unknown_proof_field": {"preserved": True}},
            "arguments": {"method": "POST", "path": "/api/services/synthetic",
                "body": {"entity_id": "update.synthetic", "enabled": False,
                         "level": 0, "optional": None},
                "verification": {"path": "/api/states/update.synthetic", "query": {},
                                 "expected": {"/body/state": "off", "/body/value": 0}}}},
        "result": {"http_status": 200, "effect_verified": True, "verification_passed": True,
                   "acknowledged": False, "automatic_retry": False, "attempts": 1,
                   "causation_verified": False, "reconciled_after_uncertain": True,
                   "last_observation": {"http_status": 200, "body": {"state": "off", "value": 0},
                                        "verification_passed": True},
                   "verification": {"exit_code": 0, "effect_verified": True},
                   "body": {"optional": None}}}


def test_compact_terminal_ledger_omits_only_display_and_preserves_action_proof_and_hashes():
    from hub.agent_context import _effect_index, _receipt_hash

    row = terminal_effect()
    before = copy.deepcopy(row)
    retained, ledger = _effect_index([row], None, compact=True)
    assert retained == [] and len(ledger) == 1
    item = ledger[0]
    assert row == before
    assert item["sequence"] == row["sequence"] and item["kind"] == row["kind"]
    assert item["status"] == row["status"] and item["approved"] is False
    assert item["model_view_only"] is True
    assert item["document"]["arguments"] == row["document"]["arguments"]
    assert item["document"]["integration_id"] == row["document"]["integration_id"]
    assert item["document"]["tool"] == row["document"]["tool"]
    expected_target = {key: value for key, value in row["document"]["target"].items()
                       if key not in {"name", "url", "port", "username"}}
    assert item["document"]["target"] == expected_target
    assert set(item["document"]) == set(row["document"]) - {"message"}
    assert "message" not in item["document"]
    assert item["result"] == row["result"]
    assert item["document_sha256"] == _receipt_hash(row["document"])
    assert item["arguments_sha256"] == _receipt_hash(row["document"]["arguments"])
    assert item["result_sha256"] == _receipt_hash(row["result"])
    assert len(json.dumps(item)) < len(json.dumps(_effect_index([row], None)[1][0])) - 300


@pytest.mark.parametrize("status", ["prepared", "dispatching", "verifying", "uncertain", "failed"])
def test_compact_ledger_never_touches_nonterminal_effects_or_latest(status):
    from hub.agent_context import _effect_index

    row = terminal_effect()
    row["status"] = status
    before = copy.deepcopy(row)
    assert _effect_index([row], None, compact=True) == ([row], [])
    assert row == before
    row = terminal_effect()
    assert _effect_index([row], row, compact=True) == ([row], [])
    row["result"]["effect_verified"] = False
    assert _effect_index([row], None, compact=True) == ([row], [])


def test_compact_verification_keeps_link_predicate_and_all_negative_proof_flags():
    from hub.agent_context import _effect_index

    row = terminal_effect(2)
    row["kind"] = "verification"
    row["document"] = {"effect_step": 1, "message": "Repeated verification description " * 10,
                       "predicate": {"path": "/api/states/update.synthetic",
                                     "expected": {"/body/state": "off", "/body/zero": 0}}}
    _, ledger = _effect_index([row], None, compact=True)
    assert ledger[0]["document"]["effect_step"] == 1
    assert ledger[0]["document"]["predicate"] == row["document"]["predicate"]
    assert ledger[0]["result"] == row["result"]
    assert ledger[0]["result"]["causation_verified"] is False
    assert ledger[0]["result"]["last_observation"]["body"]["value"] == 0


def test_minimum_fit_stage_uses_compact_terminal_ledger_without_changing_authority():
    rows = [terminal_effect(i) for i in range(1, 3)]
    rows.append({"sequence": 3, "kind": "read", "status": "succeeded",
                 "document": {"tool": "http", "integration_id": "synthetic-target",
                              "arguments": {"method": "GET", "path": "/api/states"}},
                 "result": {"http_status": 200, "body": []}})
    source = {"goal": "Synthetic bounded request", "interfaces": [{"id": "unchanged"}],
              "tools": {"http": {"unchanged": True}}, "history": rows}
    before = copy.deepcopy(source)
    fitted = fit(source, "Policy", 4000)
    assert all("message" not in item["document"] and item["model_view_only"] is True
               for item in fitted["effect_ledger"])
    assert fitted["interfaces"] == source["interfaces"] and fitted["tools"] == source["tools"]
    assert source == before
    assert len("Policy") + len(json.dumps(fitted, ensure_ascii=False, separators=(",", ":"))) < 4000


@pytest.mark.parametrize("kind,status,verified,passed", [
    ("effect", "succeeded", True, True),
    ("verification", "succeeded", False, True),
    ("effect", "succeeded", False, False),
    ("effect", "uncertain", True, True),
    ("verification", "failed", True, True),
    ("read", "succeeded", False, False),
    ("read", "succeeded", True, True),
])
def test_minimum_metadata_budget_matches_native_without_changing_latest_receipt(
    monkeypatch, kind, status, verified, passed,
):
    import hub.agent_context as context

    row = terminal_effect()
    row["kind"], row["status"] = kind, status
    row["result"].update(effect_verified=verified, verification_passed=passed)
    source = {"goal": "Mandatory unchanged authority " * 1000, "history": [row]}
    before = copy.deepcopy(source)
    actual = context._observation
    seen, observations = [], []

    def observe(entry, **limits):
        seen.append(limits["metadata_limit"])
        value = actual(entry, **limits)
        observations.append(value)
        return value

    monkeypatch.setattr(context, "_observation", observe)
    with pytest.raises(context.AgentContextLimitError):
        context.fit(source, "Policy", 2000)
    assert seen == [2500] * 4 + [1000, 600]
    assert all(item["result"] == row["result"] for item in observations)
    assert all(item["summary"]["effect_verified"] is verified for item in observations)
    assert all(item["summary"]["verification_passed"] is passed for item in observations)
    assert all(item["step_status"] == status for item in observations)
    assert observations[-1]["summary"]["result_shape"] == {"type": "object"}
    assert observations[-1]["summary"]["body_shape"] == {"type": "object"}
    assert source == before


def test_compact_terminal_metadata_keeps_literal_result_proof_and_original_hash():
    from hub.agent_context import _observation, _receipt_hash

    row = terminal_effect()
    row["kind"] = "verification"
    before = copy.deepcopy(row)
    full = _observation(row, metadata_limit=2500)
    compact = _observation(row, metadata_limit=1000)
    assert compact["result"] == full["result"] == row["result"]
    assert compact["full_sha256"] == full["full_sha256"] == _receipt_hash(row["result"])
    for key in ["http_status", "effect_verified", "verification_passed", "causation_verified"]:
        assert compact["summary"][key] == full["summary"][key] == row["result"][key]
    assert compact["step_status"] == "succeeded" and compact["model_view_only"] is True
    assert row == before
