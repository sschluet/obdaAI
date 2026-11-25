"""Desired outcomes require fresh complete goal-state proof, not an unrelated backup."""

import json
from types import SimpleNamespace

import pytest
from hub.agent_execution_state import planning_state
from hub.agent_intent import (
    EntityOutcome,
    RequestIntent,
    Requirement,
    adequacy,
    outcome_observation_targets,
)


def contract(domain="update", desired="off"):
    return RequestIntent(
        target_ids=["ha"],
        mode="admin",
        topic="general",
        requirements=[
            Requirement(
                kind="effect_postcondition",
                integration_id="ha",
                outcome=EntityOutcome(domain=domain, state=desired, scope="all_observed"),
            )
        ],
    )


def states(seq, values, domain="update", *, ws=False):
    rows = [
        {"entity_id": domain + ".synthetic_" + str(i), "state": state}
        for i, state in enumerate(values)
    ]
    return SimpleNamespace(
        sequence=seq,
        kind="read",
        status="succeeded",
        document=json.dumps(
            {
                "integration_id": "ha",
                "tool": "ha.websocket" if ws else "http",
                "arguments": {"type": "get_states", "parameters": {}}
                if ws
                else {"method": "GET", "path": "/api/states"},
            }
        ),
        result=json.dumps({"response": rows} if ws else {"http_status": 200, "body": rows}),
    )


def effect(seq):
    return SimpleNamespace(
        sequence=seq,
        kind="effect",
        status="succeeded",
        document=json.dumps(
            {
                "integration_id": "ha",
                "tool": "http",
                "arguments": {"method": "POST", "path": "/api/services/backup/create"},
            }
        ),
        result=json.dumps({"effect_verified": True}),
    )


@pytest.mark.parametrize("domain,desired", [("update", "off"), ("light", "on"), ("switch", "off")])
def test_partial_state_and_unrelated_verified_effect_do_not_complete_all_goal(domain, desired):
    intent = contract(domain, desired)
    incomplete = "on" if desired == "off" else "off"
    history = [states(1, [desired, incomplete], domain), effect(2)]
    assert not adequacy(intent, history)["satisfied"]
    assert outcome_observation_targets(intent, history) == {"ha"}
    history.append(states(3, [desired, incomplete], domain, ws=True))
    assert not adequacy(intent, history)["satisfied"]
    assert not outcome_observation_targets(intent, history)
    history += [effect(4), states(5, [desired, desired], domain)]
    assert adequacy(intent, history)["satisfied"]


@pytest.mark.parametrize("state", ["unknown", "unavailable"])
def test_unavailable_current_state_never_becomes_completed_update_goal(state):
    assert not adequacy(contract(), [states(1, ["off", state])])["satisfied"]
    with pytest.raises(ValueError):
        contract(desired=state)


def test_current_matching_state_can_prove_no_action_needed_without_inventing_effect():
    history = [states(1, ["off", "off"])]
    assert adequacy(contract(), history)["satisfied"]
    assert not any(s.kind == "effect" for s in history)
    assert planning_state(contract().model_dump(), [], remaining_effects=1)["phase"] == "observe"
    assert (
        planning_state(contract().model_dump(), [states(1, ["on"])], remaining_effects=1)["phase"]
        == "act"
    )


def test_legacy_requirement_serialization_and_effect_contract_remain_unchanged():
    old = Requirement(kind="effect_postcondition", integration_id="ha")
    assert old.model_dump() == {
        "kind": "effect_postcondition",
        "integration_id": "ha",
        "domain": "",
    }
    assert "outcome" not in old.model_dump_json()
    with pytest.raises(ValueError):
        Requirement(
            kind="system",
            integration_id="ha",
            outcome=EntityOutcome(domain="light", state="on", scope="all_observed"),
        )


def versioned(seq, rows):
    step = states(seq, [])
    step.result = json.dumps(
        {
            "http_status": 200,
            "body": [
                {"entity_id": entity, "state": state, "attributes": attrs}
                for entity, state, attrs in rows
            ],
        }
    )
    return step


def test_initial_selection_excludes_unavailable_but_requires_selected_target_versions():
    outcome = EntityOutcome(
        domain="update",
        state="off",
        scope="all_observed",
        selection_state="on",
        attribute_from_initial={"installed_version": "latest_version"},
    )
    intent = RequestIntent(
        target_ids=["ha"],
        mode="admin",
        topic="system",
        requirements=[
            Requirement(kind="effect_postcondition", integration_id="ha", outcome=outcome)
        ],
    )
    baseline = versioned(
        1,
        [
            ("update.first", "on", {"installed_version": "1", "latest_version": "2"}),
            ("update.second", "on", {"installed_version": "3", "latest_version": "4"}),
            ("update.unknown", "unavailable", {}),
        ],
    )
    post = versioned(
        3,
        [
            ("update.first", "off", {"installed_version": "2", "latest_version": "2"}),
            ("update.second", "off", {"installed_version": "3", "latest_version": "4"}),
            ("update.unknown", "unavailable", {}),
        ],
    )
    history = [baseline, effect(2), post]
    assert not adequacy(intent, history)[
        "satisfied"
    ]  # ignoring/skipping an update is not installing it
    post.result = post.result.replace('"installed_version": "3"', '"installed_version": "4"')
    assert adequacy(intent, history)["satisfied"]
    from hub.agent_outcomes import assessment

    proof = assessment(history, "ha", outcome)
    assert proof["selected_count"] == 2 and proof["initial_sequence"] == 1
    assert proof["current_sequence"] == 3 and proof["scope"] == "initial_observed_cohort"


def test_post_effect_selection_cannot_hide_remaining_or_missing_initial_entities():
    outcome = EntityOutcome(
        domain="update", state="off", scope="all_observed", selection_state="on"
    )
    initial = versioned(1, [("update.first", "on", {}), ("update.second", "on", {})])
    post = versioned(3, [("update.first", "off", {})])
    from hub.agent_outcomes import assessment

    proof = assessment([initial, effect(2), post], "ha", outcome)
    assert not proof["satisfied"] and proof["remaining_count"] == 1
    assert proof["remaining"] == [{"entity_id": "update.second", "reason": "entity_missing"}]
    assert not assessment([effect(2), post], "ha", outcome)["satisfied"]


def test_admin_entity_goal_without_bound_outcome_never_succeeds_from_minimum_effect():
    intent = RequestIntent(
        target_ids=["ha"],
        mode="admin",
        topic="system",
        requirements=[
            Requirement(kind="entity_states", domain="update", integration_id="ha"),
            Requirement(kind="effect_postcondition", integration_id="ha"),
        ],
    )
    history = [states(1, ["on", "on"]), effect(2), states(3, ["off", "on"])]
    proof = adequacy(intent, history)
    assert not proof["satisfied"] and proof["completion_binding_missing"] == ["ha"]
    assert planning_state(intent.model_dump(), history, remaining_effects=10)["phase"] == "blocked"


def test_completion_scope_never_claims_unknown_components_or_causal_installation():
    from hub.agent_outcomes import completion_summary

    intent = RequestIntent(
        target_ids=["ha"],
        mode="admin",
        topic="system",
        requirements=[
            Requirement(
                kind="effect_postcondition",
                integration_id="ha",
                outcome=EntityOutcome(
                    domain="update",
                    state="off",
                    scope="all_observed",
                    selection_state="on",
                    attribute_from_initial={"installed_version": "latest_version"},
                ),
            )
        ],
    )
    initial = versioned(
        1, [("update.first", "on", {"latest_version": "2"}), ("update.other", "unavailable", {})]
    )
    final = versioned(
        3,
        [("update.first", "off", {"installed_version": "2"}), ("update.other", "unavailable", {})],
    )
    text = completion_summary(intent, [initial, effect(2), final])
    assert text and "1 zu Beginn" in text and "Versionen" in text
    assert "1 weitere Komponenten" in text and "nicht zu dieser bestätigten Auswahl" in text
    assert "installiert" not in text and "alles" not in text


def test_required_initial_attributes_must_be_observed_before_any_target_effect():
    from hub import agent_runtime as runtime
    from hub.agent_intent import missing_initial_outcome_baseline
    from hub.agent_outcomes import assessment

    outcome = EntityOutcome(
        domain="update",
        state="off",
        scope="all_observed",
        selection_state="on",
        attribute_from_initial={"installed_version": "latest_version"},
    )
    selected = RequestIntent(
        target_ids=["ha"],
        mode="admin",
        topic="system",
        requirements=[
            Requirement(kind="effect_postcondition", integration_id="ha", outcome=outcome)
        ],
    )
    partial = versioned(1, [("update.first", "on", {})])
    proof = assessment([partial], "ha", outcome)
    assert (
        proof["reason"] == "initial_goal_attributes_missing" and proof["initial_sequence"] is None
    )
    assert missing_initial_outcome_baseline(selected, [partial], "ha")
    assert outcome_observation_targets(selected, [partial]) == {"ha"}
    with pytest.raises(PermissionError):
        runtime._effect_outcome_gate(selected, [partial], "ha")
    complete = versioned(2, [("update.first", "on", {"latest_version": "2"})])
    assert assessment([partial, complete], "ha", outcome)["initial_sequence"] == 2
    assert not missing_initial_outcome_baseline(selected, [partial, complete], "ha")
    runtime._effect_outcome_gate(selected, [partial, complete], "ha")
    assert assessment([partial, effect(2), complete], "ha", outcome)["initial_sequence"] is None


def test_requested_scalar_attributes_are_observed_without_inference_or_type_coercion():
    from hub.agent_outcomes import assessment

    outcome = EntityOutcome(
        domain="update",
        state="off",
        scope="all_observed",
        selection_state="on",
        attribute_from_initial={"build_number": "available_build"},
    )
    initial = versioned(1, [("update.first", "on", {"available_build": 0})])
    final = versioned(3, [("update.first", "off", {"build_number": False})])
    assert not assessment([initial, effect(2), final], "ha", outcome)["satisfied"]
    final = versioned(3, [("update.first", "off", {"build_number": 0})])
    assert assessment([initial, effect(2), final], "ha", outcome)["satisfied"]
