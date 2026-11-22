"""Large read histories compact without losing authority or mutation evidence."""

import copy
import hashlib
import json

from hub.agent_context import _read_index, _semantic_view, fit


def test_typed_view_keeps_projected_entities_and_actual_source_pagination_counts():
    observed = {"body": {"items": [{"/entity_id": "sensor.synthetic", "/state": "20"}],
                         "matched": 1856, "returned": 1, "next": "private-page-token"}}
    view = _semantic_view(observed, 1200)
    assert view["observed_domain_counts"] == {"sensor": 1}
    assert view["source_counts"] == {"matched": 1856, "returned": 1}
    assert view["source_has_more"] and view["items"][0]["/entity_id"] == "sensor.synthetic"
    assert "private-page-token" not in json.dumps(view)


def test_old_reads_group_by_exact_operation_with_full_hashes_not_json_prefixes():
    history = [{"kind": "read", "status": "succeeded", "sequence": i,
                "document": {"tool": "http", "integration_id": "approved",
                             "arguments": {"method": "GET", "path": "/api/states"}},
                "result": {"http_status": 200, "body": {"data": "x" * 10000}}}
               for i in range(60)]
    original = {"goal": "Use current data", "interfaces": [{"id": "approved", "revision": 3}],
                "tools": {"http": {"method": "GET"}}, "history": history, "private_context": []}
    saved = copy.deepcopy(original)
    fitted = fit(original, "Bound policy", 20000)
    assert fitted["older_read_index"] and len(fitted["history"]) == 1
    indexed = fitted["older_read_index"][0]
    assert len(indexed["receipts"]) == 59 and indexed["content_omitted"]
    first = indexed["receipts"][0]
    assert first["sequence"] == 0
    assert first["result_sha256"] == hashlib.sha256(json.dumps(
        history[0]["result"], ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    assert fitted["interfaces"] == original["interfaces"] and fitted["tools"] == original["tools"]
    assert original == saved


def test_effect_verification_failure_reconciliation_and_human_records_are_never_indexed():
    protected = [
        {"kind": "effect", "status": "succeeded", "document": {"tool": "shell"},
         "result": {"effect_verified": False, "reconciled_after_uncertain": True}},
        {"kind": "read", "status": "uncertain", "document": {"tool": "http"}, "result": {}},
        {"kind": "read", "status": "succeeded", "document": {"tool": "http.verify"},
         "result": {"verification_passed": False}},
        {"kind": "input", "status": "succeeded", "document": {"message": "Correction"},
         "result": {}},
    ]
    retained, index = _read_index(protected, None)
    assert retained == protected and not index


def test_older_effect_keeps_verification_reconciliation_target_and_original_hashes():
    effect = {"kind": "effect", "status": "succeeded", "sequence": 1,
              "document": {"tool": "shell", "integration_id": "approved",
                           "target": {"profile_revision": 3},
                           "arguments": {"command": "x" * 20000,
                                         "verification": {"path": "/api/state",
                                                          "expected": {"ok": True}}}},
              "result": {"body": "x" * 50000, "effect_verified": False, "acknowledged": True,
                         "reconciled_after_uncertain": True,
                         "verification": {"exit_code": 1, "error": "bounded synthetic error"}}}
    latest = {"kind": "read", "status": "succeeded", "sequence": 2,
              "document": {"tool": "http"}, "result": {"http_status": 200, "body": []}}
    original = {"goal": "Summarize actual evidence", "interfaces": [{"id": "approved"}],
                "tools": {"http": {}}, "history": [effect, latest], "private_context": []}
    saved = copy.deepcopy(original)
    fitted = fit(original, "Bound authority", 7000)
    older = fitted["history"][0]
    assert older["result"]["effect_verified"] is False
    assert older["result"]["acknowledged"] and older["result"]["reconciled_after_uncertain"]
    assert older["result"]["verification"]["exit_code"] == 1
    assert older["document"]["integration_id"] == "approved"
    assert older["document"]["target"] == {"profile_revision": 3}
    expected_verification = effect["document"]["arguments"]["verification"]
    assert older["document"]["arguments"]["verification"] == expected_verification
    for key, value in [("result", effect["result"]), ("document", effect["document"])]:
        assert older[key]["full_sha256"] == hashlib.sha256(json.dumps(
            value, ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest()
    assert original == saved and fitted["interfaces"] == original["interfaces"]
