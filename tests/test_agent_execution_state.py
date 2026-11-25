"""No-progress tracking remains target-bound and never retries uncertain effects."""

import json
from types import SimpleNamespace

from hub.agent_execution_state import duplicate_read, planning_state, progress_anchor
from hub.agent_intent import RequestIntent, Requirement


def step(seq, *, target="ha", kind="read", status="succeeded", verified=False, path="/api/config"):
    return SimpleNamespace(
        sequence=seq,
        kind=kind,
        status=status,
        document=json.dumps(
            {"integration_id": target, "tool": "http", "arguments": {"method": "GET", "path": path}}
        ),
        result=json.dumps(
            {"http_status": 200, "body": {"version": "synthetic"}, "effect_verified": verified}
        ),
    )


def test_identical_admin_read_is_reused_but_same_target_effect_allows_fresh_read():
    original = step(1)
    args = json.loads(original.document)["arguments"]
    assert duplicate_read([original], "ha", "http", args) == 1
    unrelated = step(2, target="other", kind="effect", verified=True)
    assert duplicate_read([original, unrelated], "ha", "http", args) == 1
    changed = step(3, kind="effect", verified=True)
    assert duplicate_read([original, unrelated, changed], "ha", "http", args) is None
    assert duplicate_read([original, changed, step(4)], "ha", "http", args) == 4
    assert duplicate_read([original], "ha", "http.verify", args) is None


def test_repeated_observation_is_not_progress_and_failed_reads_cannot_reset_repairs():
    history = [step(1), step(3), step(5, status="failed")]
    assert progress_anchor(history) == 1
    history += [step(6, kind="effect", status="uncertain")]
    assert progress_anchor(history) == 1
    history += [step(7, kind="effect", verified=True), step(8)]
    assert progress_anchor(history) == 8


def test_execution_phase_comes_from_actual_missing_evidence_and_effects():
    intent = RequestIntent(
        target_ids=["ha"],
        mode="admin",
        topic="system",
        requirements=[
            Requirement(kind="system", integration_id="ha"),
            Requirement(kind="effect_postcondition", integration_id="ha"),
        ],
    ).model_dump()
    assert planning_state(intent, [], remaining_effects=2)["phase"] == "observe"
    assert planning_state(intent, [step(1)], remaining_effects=2)["phase"] == "act"
    assert planning_state(intent, [step(1)], remaining_effects=0)["phase"] == "blocked"
    uncertain = step(2, kind="effect", status="uncertain")
    state = planning_state(intent, [step(1), uncertain], remaining_effects=1)
    assert state["phase"] == "verify" and state["unresolved_effects"][0]["sequence"] == 2
    state = planning_state(
        intent, [step(1), step(2, kind="effect", verified=True)], remaining_effects=1
    )
    assert state["phase"] == "assess_completion"
    assert "not proof" in state["instruction"]


def test_target_exhaustion_is_not_hidden_by_remaining_budget_at_other_targets():
    from hub.agent_execution_state import remaining_budget

    intent = RequestIntent(
        target_ids=["ha"],
        mode="admin",
        topic="system",
        requirements=[Requirement(kind="effect_postcondition", integration_id="ha")],
    ).model_dump()
    budget = remaining_budget([], 12, {"ha": 0, "other": 10})
    assert budget["remaining_effects"] == 12
    assert planning_state(intent, [], **budget)["phase"] == "blocked"
