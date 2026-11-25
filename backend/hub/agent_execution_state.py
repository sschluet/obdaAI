"""Receipt-derived loop guidance. Never dispatches or grants execution authority."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from hub.action_api import encode
from hub.agent_failures import read_result_failure


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def duplicate_read(
    history: Sequence[Any],
    integration_id: str,
    tool: str,
    arguments: Mapping[str, Any],
) -> int | None:
    """Return unchanged successful observation, allowing refresh after target effects.

    Explicit http.verify polling is deliberately outside this comparison. An effect
    at another target does not make this target's identical observation new evidence.
    """
    if not (tool == "http" and arguments.get("method") == "GET"):
        return None
    barrier = max(
        (
            step.sequence
            for step in history
            if step.kind == "effect"
            and step.status in {"dispatching", "verifying", "succeeded", "uncertain"}
            and _object(step.document).get("integration_id") == integration_id
        ),
        default=0,
    )
    for step in reversed(history):
        if step.sequence <= barrier or step.kind != "read" or step.status != "succeeded":
            continue
        document, result = _object(step.document), _object(step.result)
        if (
            document.get("integration_id") == integration_id
            and document.get("tool") == tool
            and read_result_failure(tool, result) is None
            and encode(document.get("arguments")) == encode(dict(arguments))
        ):
            return int(step.sequence)
    return None


def progress_anchor(history: Sequence[Any]) -> int:
    """Bound repair episodes to real new observations or independently verified effects."""
    seen: set[str] = set()
    anchor = 0
    epochs: dict[str, int] = {}
    for step in history:
        document, result = _object(step.document), _object(step.result)
        identifier = document.get("integration_id", "")
        if not isinstance(identifier, str):
            continue
        if step.kind == "effect":
            epochs[identifier] = step.sequence
            if step.status == "succeeded" and result.get("effect_verified") is True:
                anchor = step.sequence
        elif (
            step.kind == "read"
            and step.status == "succeeded"
            and isinstance(document.get("tool"), str)
            and read_result_failure(document["tool"], result) is None
        ):
            fingerprint = encode(
                [
                    identifier,
                    epochs.get(identifier, 0),
                    document.get("tool"),
                    document.get("arguments"),
                ]
            )
            if fingerprint not in seen:
                seen.add(fingerprint)
                anchor = step.sequence
    return anchor


def remaining_budget(
    history: Sequence[Any],
    maximum: int,
    target_limits: Mapping[str, int],
) -> dict[str, Any]:
    spent = [
        step
        for step in history
        if step.kind == "effect"
        and step.status in {"dispatching", "verifying", "succeeded", "uncertain"}
    ]
    remaining = max(0, maximum - len(spent))
    return {
        "remaining_effects": remaining,
        "target_remaining_effects": {
            identifier: max(
                0,
                min(
                    remaining,
                    limit
                    - sum(
                        _object(step.document).get("integration_id") == identifier for step in spent
                    ),
                ),
            )
            for identifier, limit in target_limits.items()
        },
    }


def planning_state(
    intent: Mapping[str, Any] | None,
    history: Sequence[Any],
    *,
    remaining_effects: int,
    target_remaining_effects: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Separate observations, requested changes and their verification in model context."""
    from hub.agent_intent import adequacy, outcome_observation_targets

    evidence = adequacy(intent, history) if intent else None
    missing = evidence["missing"] if evidence else []
    missing_reads = [r for r in missing if r["kind"] != "effect_postcondition"]
    missing_changes = [r for r in missing if r["kind"] == "effect_postcondition"]
    observation_targets = outcome_observation_targets(intent, history)
    for requirement in missing_changes:
        if requirement.get("outcome") and requirement["integration_id"] in observation_targets:
            missing_reads.append(
                {
                    "kind": "entity_states",
                    "integration_id": requirement["integration_id"],
                    "domain": requirement["outcome"]["domain"],
                }
            )
    unresolved = []
    verified = []
    for step in history:
        if step.kind != "effect":
            continue
        document, result = _object(step.document), _object(step.result)
        receipt = {
            "sequence": step.sequence,
            "integration_id": document.get("integration_id"),
            "status": step.status,
        }
        if step.status == "succeeded" and result.get("effect_verified") is True:
            verified.append(receipt)
        elif step.status in {"dispatching", "verifying", "succeeded", "uncertain"}:
            unresolved.append(receipt)
    change_possible = remaining_effects > 0 and any(
        target_remaining_effects is None
        or target_remaining_effects.get(item["integration_id"], 0) > 0
        for item in missing_changes
    )
    phase = (
        "verify"
        if unresolved
        else "observe"
        if missing_reads
        else "blocked"
        if evidence and evidence.get("completion_binding_missing")
        else "act"
        if missing_changes and change_possible
        else "blocked"
        if missing_changes
        else "assess_completion"
    )
    from hub.agent_intent import RequestIntent
    from hub.agent_outcomes import assessment

    outcomes = (
        [
            {
                "integration_id": item.integration_id,
                **assessment(
                    history,
                    item.integration_id,
                    item.outcome,
                ),
            }
            for item in RequestIntent.model_validate(intent).requirements
            if item.outcome is not None
        ]
        if intent
        else []
    )
    return {
        "outcomes": outcomes,
        "completion_binding_missing": evidence.get("completion_binding_missing", [])
        if evidence
        else [],
        "version": 1,
        "phase": phase,
        "missing_observations": missing_reads,
        "missing_changes": missing_changes,
        "verified_effects": verified[-12:],
        "unresolved_effects": unresolved[-12:],
        "remaining_effects": max(0, remaining_effects),
        **(
            {"target_remaining_effects": dict(target_remaining_effects)}
            if target_remaining_effects is not None
            else {}
        ),
        "instruction": (
            "Follow the phase using current allowed tools. Reuse successful observations; "
            "do not repeat an identical GET without an intervening change at that target. "
            "Observe missing evidence, perform only explicitly requested authorized changes, "
            "then independently verify each result. A backup or unrelated verified change "
            "does not complete another requested outcome. Minimum evidence is not proof "
            "that every part of the goal is complete. Unresolved effects prohibit repetition. "
            "This guidance grants no permissions and supplies no tool arguments."
        ),
    }
