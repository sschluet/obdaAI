"""Check semantic desired states against a frozen, originally observed cohort."""

import json
from collections.abc import Sequence
from typing import Any

from hub.agent_ha_evidence import states_snapshot


def assessment(history: Sequence[Any], identifier: str, outcome: Any) -> dict[str, Any]:
    first_effect = min(
        (
            s.sequence
            for s in history
            if s.kind == "effect"
            and (
                not _document(s).get("integration_id")
                or _document(s).get("integration_id") == identifier
            )
        ),
        default=float("inf"),
    )
    attributes = list(
        dict.fromkeys(
            [
                *outcome.attribute_from_initial,
                *outcome.attribute_from_initial.values(),
            ]
        )
    )
    initial = None
    incomplete_attributes = False
    for step in sorted(history, key=lambda s: s.sequence):
        if step.sequence >= first_effect:
            break
        candidate = states_snapshot([step], identifier, outcome.domain, attribute_names=attributes)
        if candidate is not None:
            cohort = [
                row
                for row in candidate["entities"]
                if outcome.selection_state is None or row["state"] == outcome.selection_state
            ]
            if all(
                all(
                    source in row["attributes"] and row["attributes"][source] is not None
                    for source in outcome.attribute_from_initial.values()
                )
                for row in cohort
            ):
                initial = candidate
                break
            incomplete_attributes = True
    current = states_snapshot(history, identifier, outcome.domain, attribute_names=attributes)
    result: dict[str, Any] = {
        "satisfied": False,
        "domain": outcome.domain,
        "scope": "initial_observed_cohort",
        "selected_count": 0,
        "remaining_count": None,
        "remaining": [],
        "initial_sequence": initial["sequence"] if initial else None,
        "current_sequence": current["sequence"] if current else None,
    }
    if initial is None:
        result["reason"] = (
            "initial_goal_attributes_missing"
            if incomplete_attributes
            else "initial_complete_snapshot_missing"
        )
        return result
    selected = [
        row
        for row in initial["entities"]
        if outcome.selection_state is None or row["state"] == outcome.selection_state
    ]
    result["selected_count"] = len(selected)
    selected_ids = {row["entity_id"] for row in selected}
    result["outside_selected_unknown_count"] = (
        sum(
            row["entity_id"] not in selected_ids and row["state"] in {"unknown", "unavailable"}
            for row in current["entities"]
        )
        if current
        else None
    )
    if current is None:
        result["reason"] = "fresh_complete_snapshot_missing"
        return result
    observed = {row["entity_id"]: row for row in current["entities"]}
    remaining = []
    for row in selected:
        actual = observed.get(row["entity_id"])
        reason = (
            "entity_missing"
            if actual is None
            else "state_not_reached"
            if actual["state"] != outcome.state
            else ""
        )
        if not reason and actual is not None:
            for destination, source in outcome.attribute_from_initial.items():
                expected = row["attributes"].get(source)
                value = actual["attributes"].get(destination)
                if (
                    source not in row["attributes"]
                    or expected is None
                    or destination not in actual["attributes"]
                    or type(value) is not type(expected)
                    or value != expected
                ):
                    reason = "observed_attribute_postcondition_missing"
                    break
        if reason:
            remaining.append({"entity_id": row["entity_id"], "reason": reason})
    result.update(
        satisfied=not remaining,
        remaining_count=len(remaining),
        remaining=remaining[:50],
        omitted_remaining=max(0, len(remaining) - 50),
        initial_result_sha256=initial["result_sha256"],
        current_result_sha256=current["result_sha256"],
    )
    return result


def _document(step: Any) -> dict[str, Any]:
    try:
        value = json.loads(step.document)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def completion_summary(intent: Any, history: Sequence[Any]) -> str | None:
    """Report only proven typed outcomes, never repeat a model's blanket success claim."""
    from hub.agent_intent import RequestIntent

    selected = RequestIntent.model_validate(intent)
    typed = [item for item in selected.requirements if item.outcome is not None]
    if not typed:
        return None
    labels = {"update": "Updates", "light": "Lichter", "switch": "Schalter"}
    lines = []
    for item in typed:
        outcome = item.outcome
        assert outcome is not None
        proof = assessment(history, item.integration_id, outcome)
        if not proof["satisfied"]:
            return None
        count = proof["selected_count"]
        label = labels.get(outcome.domain, "Einträge")
        if count:
            condition = (
                "der vorgesehene Zustand und die vorgesehenen Versionen"
                if outcome.attribute_from_initial.get("installed_version") == "latest_version"
                else "der vorgesehene Zustand"
            )
            lines.append(
                f"Für die {count} zu Beginn ausgewählten {label} ist {condition} bestätigt."
            )
        else:
            lines.append(
                "Im vollständig abgefragten Anfangsbestand gehörten keine Einträge "
                "zur angefragten Auswahl."
            )
        unknown = proof["outside_selected_unknown_count"]
        if unknown:
            lines.append(
                f"Für {unknown} weitere Komponenten ist kein Status verfügbar; "
                "sie gehören nicht zu dieser bestätigten Auswahl."
            )
    return "\n".join(lines)


def automatic_completion(intent: Any, history: Sequence[Any]) -> str | None:
    """Finish a purely declarative state goal once its complete original proof exists.

    Content answers and other targets still require their normal response path.
    This does not plan a tool, skip an effect check, or infer user instructions.
    """
    from hub.agent_intent import RequestIntent, adequacy

    selected = RequestIntent.model_validate(intent)
    if any(
        step.kind in {"read", "effect"}
        and step.status
        in {
            "prepared",
            "dispatching",
            "verifying",
            "uncertain",
        }
        for step in history
    ):
        return None
    if selected.mode != "admin" or any(
        item.kind
        not in {
            "connection",
            "system",
            "entity_states",
            "effect_postcondition",
        }
        for item in selected.requirements
    ):
        return None
    typed_targets = {
        item.integration_id
        for item in selected.requirements
        if item.kind == "effect_postcondition" and item.outcome is not None
    }
    if typed_targets != set(selected.target_ids) or not adequacy(selected, history)["satisfied"]:
        return None
    return completion_summary(selected, history)
