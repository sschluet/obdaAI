"""Closed explicit all-update requests strengthen evidence without choosing actions or rights."""

from types import SimpleNamespace

import pytest
from hub.agent_intent import EntityOutcome, RequestIntent, Requirement, normalize_goal

GOAL = "Bitte prüfe Home Assistant und spiele alle ausstehenden Update ein"
PROFILES = {"ha": SimpleNamespace(kind="home_assistant", enabled=True)}


def intent(outcome=None, **updates):
    return RequestIntent(
        mode="admin",
        topic="system",
        target_ids=["ha"],
        requirements=[
            Requirement(kind="effect_postcondition", integration_id="ha", outcome=outcome),
            Requirement(kind="entity_states", integration_id="ha", domain="update"),
            Requirement(kind="entity_states", integration_id="ha", domain="update"),
        ],
        **updates,
    )


@pytest.mark.parametrize(
    "goal",
    [
        GOAL,
        "Bitte prüfe Home Assistant und spiele alle ausstehenden Updates ein.",
        "Installiere alle ausstehenden Updates in Home Assistant.",
        "Check Home Assistant and install all pending updates.",
    ],
)
def test_closed_bound_admin_gets_initial_cohort_version_proof_and_only_exact_dedup(goal):
    original = intent()
    result = normalize_goal(original, PROFILES, goal)
    assert result.mode == "admin" and result.target_ids == ["ha"]
    assert len(result.requirements) == 2
    outcome = result.requirements[0].outcome
    assert outcome == EntityOutcome(
        domain="update",
        state="off",
        scope="all_observed",
        selection_state="on",
        attribute_from_initial={"installed_version": "latest_version"},
    )
    assert original.requirements[0].outcome is None and len(original.requirements) == 3


@pytest.mark.parametrize(
    "goal",
    [
        "Bitte prüfe Home Assistant und spiele keine ausstehenden Updates ein.",
        "Bitte prüfe Home Assistant und spiele alle ausstehenden Updates nicht ein.",
        "Bitte prüfe Home Assistant und spiele alle ausstehenden Updates ein "
        "und lösche alte Sicherungen.",
        "Bitte prüfe Home Assistant und spiele alle ausstehenden Updates bis Version 2026.10 ein.",
        "Bitte plane, wie ich alle ausstehenden Updates in Home Assistant einspielen könnte.",
        "Erkläre bitte, wie alle ausstehenden Updates eingespielt werden.",
        "Bitte prüfe Paperless und spiele alle ausstehenden Updates ein.",
        "Bitte spiele das Update der Küchenlampe ein.",
    ],
)
def test_negative_compound_version_pinned_and_other_target_goals_are_not_rewritten(goal):
    original = intent()
    assert normalize_goal(original, PROFILES, goal) == original


@pytest.mark.parametrize(
    "change", ["observe", "uncertain", "other_kind", "disabled", "multiple", "noeffect"]
)
def test_no_goal_proof_or_target_authority_is_invented(change):
    original = intent()
    profiles = PROFILES
    if change == "observe":
        original = original.model_copy(update={"mode": "observe"})
    elif change == "uncertain":
        original = original.model_copy(update={"confidence": "uncertain"})
    elif change == "other_kind":
        profiles = {"ha": SimpleNamespace(kind="paperless", enabled=True)}
    elif change == "disabled":
        profiles = {"ha": SimpleNamespace(kind="home_assistant", enabled=False)}
    elif change == "multiple":
        original = original.model_copy(update={"target_ids": ["ha", "other"]})
    else:
        original = original.model_copy(update={"requirements": original.requirements[1:]})
    result = normalize_goal(original, profiles, GOAL)
    assert all(r.outcome is None for r in result.requirements)
    assert result.target_ids == original.target_ids and result.mode == original.mode


@pytest.mark.parametrize(
    "updates",
    [
        {"selection_state": "off"},
        {"state": "on"},
        {"domain": "light", "attribute_from_initial": {}},
        {"attribute_from_initial": {}},
    ],
)
def test_conflicting_nonnull_model_proof_cannot_weaken_closed_update_goal(updates):
    valid = EntityOutcome(
        domain="update",
        state="off",
        scope="all_observed",
        selection_state="on",
        attribute_from_initial={"installed_version": "latest_version"},
    )
    with pytest.raises(ValueError, match="conflicts"):
        normalize_goal(intent(valid.model_copy(update=updates)), PROFILES, GOAL)
