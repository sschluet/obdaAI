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
