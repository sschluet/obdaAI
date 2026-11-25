"""Compact duplicate planning metadata while preserving full conditions and receipts."""

from copy import deepcopy

from hub.agent_context import fit


def test_derived_goal_and_phase_views_reference_the_unchanged_full_goal_contract():
    predicate = {
        "kind": "effect_postcondition",
        "integration_id": "ha",
        "domain": "",
        "outcome": {
            "domain": "update",
            "state": "off",
            "scope": "all_observed",
            "selection_state": "on",
            "attribute_from_initial": {"installed_version": "latest_version"},
        },
    }
    data = {
        "goal": "Synthetic goal",
        "request_contract": {"requirements": [predicate]},
        "interfaces": [{"integration_id": "ha", "rules": {"enabled": True}}],
        "read_only": False,
        "history": [],
        "goal_evidence": {
            "satisfied": False,
            "missing": [predicate],
            "instruction": "Repeated guidance " * 500,
        },
        "execution_state": {
            "phase": "verify",
            "remaining_effects": 1,
            "unresolved_effects": [{"sequence": 4, "integration_id": "ha", "status": "uncertain"}],
            "instruction": "Derived phase guidance " * 500,
            "missing_observations": [],
            "outcomes": [],
        },
    }
    original = deepcopy(data)
    result = fit(data, "Synthetic policy", 2500)
    assert result["request_contract"] == original["request_contract"]
    assert result["interfaces"] == original["interfaces"] and not result["read_only"]
    assert not result["goal_evidence"]["satisfied"]
    assert result["goal_evidence"]["missing"][0]["outcome_source"] == "request_contract"
    assert result["goal_evidence"]["model_view_only"]
    assert (
        result["execution_state"]["unresolved_effects"]
        == original["execution_state"]["unresolved_effects"]
    )
    assert data == original


def test_last_stage_omits_only_repeated_discovery_copy_not_operations_or_rules():
    data = {
        "goal": "Synthetic",
        "history": [],
        "interfaces": [
            {
                "integration_id": "ha",
                "rules": {"http_methods": ["GET", "POST"]},
                "capabilities": {
                    "operations": {"http_prefixes": ["/api/"]},
                    "readiness": {"live_access_verified": False},
                    "discovery": ["Repeated app-authored hint " * 500],
                },
            }
        ],
    }
    original = deepcopy(data)
    result = fit(data, "Synthetic policy", 2500)
    assert result["interfaces"][0]["rules"] == original["interfaces"][0]["rules"]
    actual = result["interfaces"][0]["capabilities"]
    assert actual["operations"] == original["interfaces"][0]["capabilities"]["operations"]
    assert actual["readiness"] == {"live_access_verified": False}
    assert actual["discovery_omitted"] == 1 and actual["model_view_only"]
    assert len(actual["full_sha256"]) == 64 and data == original
