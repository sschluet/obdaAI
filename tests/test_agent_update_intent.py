"""Update claims require actual update-state evidence, never version metadata alone."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from hub.agent_intent import (
    RequestIntent,
    Requirement,
    accept_semantic,
    adequacy,
    infer,
    normalize_goal,
    semantic_request,
    update_overview_goal,
)

HA = "synthetic-ha"
GOAL = "Welche Updates stehen in Home Assistant aus?"


def profiles(kind="home_assistant", enabled=True):
    return {HA: SimpleNamespace(id=HA, kind=kind, name="Synthetic Home Assistant", enabled=enabled)}


def intent(*requirements, mode="observe", confidence="certain", freshness="current", **kwargs):
    return RequestIntent(
        target_ids=[HA],
        mode=mode,
        topic="system",
        confidence=confidence,
        freshness=freshness,
        requirements=list(requirements) or [Requirement(kind="system", integration_id=HA)],
        **kwargs,
    )


def update():
    return Requirement(kind="entity_states", domain="update", integration_id=HA)


def receipt(path="/api/config", body=None, *, sequence=1, tool="http", arguments=None):
    args = arguments or {"method": "GET", "path": path}
    result = {"http_status": 200, "body": {"version": "synthetic"} if body is None else body}
    if tool == "ha.websocket":
        result = {"response": body}
    return SimpleNamespace(
        kind="read",
        status="succeeded",
        sequence=sequence,
        document=json.dumps({"tool": tool, "integration_id": HA, "arguments": args}),
        result=json.dumps(result),
    )


def test_unknown_ha_read_shortcut_defers_instead_of_using_unspecified_evidence():
    assert infer("Welche Updates stehen in Home Assistant aus?", profiles()) is None
    assert infer("Zeige die verfügbaren Integrationen in Home Assistant", profiles()) is None
    known = infer("Welche Lampen habe ich in Home Assistant?", profiles())
    assert known and [(r.kind, r.domain) for r in known.requirements] == [
        ("entity_states", "light")
    ]


@pytest.mark.parametrize("weak", ["system", "unspecified", "updates"])
def test_pure_update_goal_canonicalizes_weak_or_plural_alias_without_authority_changes(weak):
    required = (
        Requirement(kind="entity_states", domain="updates", integration_id=HA)
        if weak == "updates"
        else Requirement(kind=weak, integration_id=HA)
    )
    original = intent(required)
    before = original.model_dump()
    fixed = normalize_goal(original, profiles(), GOAL)
    assert fixed.requirements == [update()]
    assert original.model_dump() == before
    for key in ["mode", "target_ids", "research", "confidence", "freshness"]:
        assert fixed.model_dump()[key] == before[key]
    assert normalize_goal(fixed, profiles(), GOAL) == fixed
    assert update_overview_goal(GOAL, fixed)


def test_semantic_acceptance_is_goal_bound_and_goal_optional_compatibility_is_preserved():
    payload = intent().model_dump()
    accepted = accept_semantic(payload, profiles(), goal=GOAL)
    assert accepted.origin == "semantic" and accepted.requirements == [update()]
    assert accept_semantic(payload, profiles()).requirements[0].kind == "system"


@pytest.mark.parametrize(
    "goal",
    [
        GOAL,
        "Was für Updates sind in HA verfügbar?",
        "Wie viele Updates sind verfügbar?",
        "Liste alle Updates in Home Assistant auf.",
        "Show available updates in Home Assistant",
        "What updates are available in HA?",
    ],
)
def test_pure_update_overviews_are_renderer_eligible_without_a_tool_shortcut(goal):
    fixed = normalize_goal(intent(), profiles(), goal)
    assert fixed.requirements == [update()]
    assert update_overview_goal(goal, fixed)
    assert not hasattr(fixed, "inventory_plan")


@pytest.mark.parametrize(
    "goal",
    [
        "Welche Updates stehen in Home Assistant aus und welche Risiken haben sie?",
        "Welche Updates stehen in Home Assistant aus? Analysiere sie.",
        "Vergleiche verfügbare Updates in Home Assistant.",
        "Wie installiere ich Updates in Home Assistant?",
        "Welche Updates waren letzte Woche in Home Assistant verfügbar?",
        "Liste verfügbare Updates für ein bestimmtes Add-on in Home Assistant.",
        "Prüfe verfügbare Updates und installiere sie in Home Assistant.",
    ],
)
def test_analysis_filters_history_and_mixed_goals_are_not_replaced_by_a_metadata_list(goal):
    fixed = normalize_goal(intent(), profiles(), goal)
    assert not update_overview_goal(goal, fixed)


def test_admin_and_mixed_read_contract_preserves_every_effect_and_other_requirement():
    old = intent(
        Requirement(kind="system", integration_id=HA),
        Requirement(kind="entity_states", domain="sensor", integration_id=HA),
        Requirement(kind="effect_postcondition", integration_id=HA),
        mode="admin",
    )
    fixed = normalize_goal(old, profiles(), "Prüfe verfügbare Updates und installiere sie in HA.")
    assert fixed.requirements[:-1] == old.requirements
    assert fixed.requirements[-1] == update()
    assert fixed.mode == old.mode and fixed.target_ids == old.target_ids
    assert not update_overview_goal(GOAL, fixed)


def test_pure_update_question_does_not_drop_other_domain_requirement():
    old = intent(Requirement(kind="entity_states", domain="light", integration_id=HA))
    fixed = normalize_goal(old, profiles(), GOAL)
    assert fixed.requirements == [*old.requirements, update()]
    assert not update_overview_goal(GOAL, fixed)


@pytest.mark.parametrize(
    "case",
    [
        "historical",
        "uncertain",
        "explain",
        "other_kind",
        "disabled",
        "unselected",
        "version_only",
        "tutorial",
        "services",
    ],
)
def test_normalization_never_creates_targets_rights_or_historical_public_current_facts(case):
    original = intent()
    selected, goal = profiles(), GOAL
    if case == "historical":
        original = intent(freshness="historical")
    elif case == "uncertain":
        original = intent(confidence="uncertain")
    elif case == "explain":
        original = RequestIntent(target_ids=[], mode="explain", topic="general")
    elif case == "other_kind":
        selected = profiles("ssh")
    elif case == "disabled":
        selected = profiles(enabled=False)
    elif case == "unselected":
        selected = {"another": next(iter(profiles().values()))}
    elif case == "version_only":
        goal = "Welche Version hat Home Assistant?"
    elif case == "tutorial":
        goal = "Wie installiere ich Updates in Home Assistant?"
    else:
        goal = "Welche Update-Services sind in Home Assistant verfügbar?"
    assert normalize_goal(original, selected, goal) == original


def test_only_already_selected_ha_targets_gain_evidence_not_ssh_or_other_accounts():
    selected = {
        **profiles(),
        "ssh": SimpleNamespace(kind="ssh", enabled=True),
        "unused": SimpleNamespace(kind="home_assistant", enabled=True),
    }
    old = RequestIntent(
        target_ids=[HA, "ssh"],
        mode="admin",
        topic="system",
        requirements=[
            Requirement(kind="system", integration_id="ssh"),
            Requirement(kind="effect_postcondition", integration_id="ssh"),
            Requirement(kind="system", integration_id=HA),
        ],
    )
    before = deepcopy(old.model_dump())
    fixed = normalize_goal(old, selected, "Prüfe verfügbare Updates in HA und den SSH-Server.")
    assert fixed.target_ids == old.target_ids and old.model_dump() == before
    assert fixed.requirements == [*old.requirements, update()]
    assert not update_overview_goal(GOAL, fixed)


def test_configuration_and_supervisor_metadata_cannot_prove_update_inventory():
    fixed = normalize_goal(intent(), profiles(), GOAL)
    config = receipt()
    supervisor = receipt(
        tool="ha.websocket",
        arguments={"type": "supervisor/api", "parameters": {}},
        body={"version": "synthetic", "addons": []},
        sequence=2,
    )
    assert adequacy(fixed, [config, supervisor])["satisfied"] is False
    assert adequacy(fixed, [config, supervisor])["missing"] == [update().model_dump()]


@pytest.mark.parametrize("ws", [False, True])
@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"entity_id": "update.synthetic", "state": "off"}],
        [{"entity_id": "update.synthetic", "state": "on"}],
    ],
)
def test_complete_actual_http_or_ws_states_prove_update_requirement(ws, rows):
    fixed = normalize_goal(intent(), profiles(), GOAL)
    observed = (
        receipt(tool="ha.websocket", arguments={"type": "get_states", "parameters": {}}, body=rows)
        if ws
        else receipt("/api/states", rows)
    )
    assert adequacy(fixed, [observed])["satisfied"] is True


def test_truncated_projection_does_not_establish_no_pending_updates():
    args = {
        "method": "GET",
        "path": "/api/states",
        "projection": {
            "items_path": "",
            "where_pointer": "/entity_id",
            "where_prefix": "update.",
            "where_equals": None,
            "fields": ["/entity_id", "/state"],
            "limit": 1,
        },
    }
    result = {
        "items": [{"/entity_id": "update.synthetic", "/state": "off"}],
        "matched": 2,
        "returned": 1,
    }
    fixed = normalize_goal(intent(), profiles(), GOAL)
    assert not adequacy(fixed, [receipt("/api/states", result, arguments=args)])["satisfied"]


def test_non_update_domain_does_not_use_new_complete_update_evidence_contract(monkeypatch):
    import hub.agent_ha_evidence as evidence

    monkeypatch.setattr(
        evidence, "evidence_satisfied", lambda *a, **kw: pytest.fail("update-only helper")
    )
    lights = intent(Requirement(kind="entity_states", domain="light", integration_id=HA))
    assert adequacy(
        lights, [receipt("/api/states", [{"entity_id": "light.synthetic", "state": "on"}])]
    )["satisfied"]


def test_semantic_contract_describes_update_states_and_version_evidence_limit():
    request = semantic_request(GOAL, profiles())
    assert "domain update" in request["instruction"]
    assert "metadata alone does not establish" in request["instruction"]
    assert (
        "on=update available"
        in request["data"]["kind_hints"]["home_assistant"]["domain_semantics"]["update"]
    )


def test_update_adequacy_explains_complete_domain_without_changing_requirement_schema():
    fixed = normalize_goal(intent(), profiles(), GOAL)
    result = adequacy(fixed, [receipt()])
    assert result["missing"] == [update().model_dump()]
    assert result["complete_domain_evidence"] == [
        {"integration_id": HA, "domain": "update", "required": "complete_domain_snapshot"}
    ]
    assert "partial/per-entity samples" in result["instruction"]
    assert "Supervisor metadata alone does not prove" in result["instruction"]
    assert "/api/" not in result["instruction"]
    assert "complete_domain_evidence" not in Requirement.model_fields
    ordinary = adequacy(
        intent(Requirement(kind="entity_states", domain="light", integration_id=HA)), []
    )
    assert set(ordinary) == {"satisfied", "missing", "instruction"}


def effect(target=HA, *, sequence=2, verified=True, status="succeeded"):
    return SimpleNamespace(
        kind="effect",
        status=status,
        sequence=sequence,
        document=json.dumps(
            {
                "integration_id": target,
                "tool": "http",
                "arguments": {"method": "POST", "path": "/api/synthetic"},
            }
        ),
        result=json.dumps({"effect_verified": verified}),
    )


def test_verified_effect_refresh_targets_are_missing_data_only_and_fresh_read_clears_them():
    from hub.agent_intent import post_effect_read_targets

    selected = intent(
        update(), Requirement(kind="effect_postcondition", integration_id=HA), mode="admin"
    )
    before = deepcopy(selected.model_dump())
    old = receipt("/api/states", [{"entity_id": "update.synthetic", "state": "on"}], sequence=1)
    assert post_effect_read_targets(selected, [old]) == set()
    assert post_effect_read_targets(selected, [old, effect()]) == {HA}
    fresh = receipt("/api/states", [{"entity_id": "update.synthetic", "state": "off"}], sequence=3)
    assert post_effect_read_targets(selected, [old, effect(), fresh]) == set()
    assert selected.model_dump() == before
    assert adequacy(selected, [old, effect(), fresh])["satisfied"]


@pytest.mark.parametrize(
    "verified,status",
    [
        (False, "succeeded"),
        (1, "succeeded"),
        (True, "prepared"),
        (True, "uncertain"),
        (True, "failed"),
    ],
)
def test_unverified_or_uncertain_effect_does_not_create_a_refresh_grant(verified, status):
    from hub.agent_intent import post_effect_read_targets

    assert (
        post_effect_read_targets(intent(update()), [effect(verified=verified, status=status)])
        == set()
    )


def test_effect_only_and_other_target_effect_never_create_a_read_deadlock_or_new_target():
    from hub.agent_intent import post_effect_read_targets

    only_effect = intent(Requirement(kind="effect_postcondition", integration_id=HA), mode="admin")
    assert post_effect_read_targets(only_effect, [effect()]) == set()
    assert post_effect_read_targets(intent(update()), [effect("unselected")]) == set()
    assert post_effect_read_targets(None, [effect()]) == set()
    selected = RequestIntent(
        target_ids=[HA, "other"],
        mode="admin",
        topic="general",
        requirements=[
            update(),
            Requirement(kind="system", integration_id="other"),
            Requirement(kind="effect_postcondition", integration_id=HA),
        ],
    )
    assert post_effect_read_targets(selected, [effect()]) == {HA}


def test_refresh_helper_preserves_full_read_contract_and_authority_fields(monkeypatch):
    import hub.agent_intent as module

    selected = intent(
        Requirement(kind="system", integration_id=HA),
        Requirement(kind="effect_postcondition", integration_id=HA),
        mode="admin",
        research=True,
        followup=True,
    )
    before = deepcopy(selected.model_dump())
    history = [effect()]
    calls = []

    def proof(read_view, observed):
        calls.append(read_view.model_dump())
        assert observed is history
        return {"missing": [{"integration_id": HA}]}

    monkeypatch.setattr(module, "adequacy", proof)
    assert module.post_effect_read_targets(selected, history) == {HA}
    assert selected.model_dump() == before
    expected = {**before, "requirements": [before["requirements"][0]]}
    assert calls == [expected]
