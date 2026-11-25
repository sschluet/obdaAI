"""Useful partial outcomes from durable receipts; failure never becomes success."""

import json
from collections.abc import Sequence
from typing import Any

from hub.agent_ha_evidence import states_snapshot


def _object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def terminal_summary(job: Any, history: Sequence[Any], status: str, message: str) -> str:
    """Add small factual progress to failed jobs without echoing target/model prose.

    Original failure/uncertainty is preserved. A complete, current source receipt
    may explain what was learned; it cannot prove an administration goal finished.
    """
    if status not in {"failed", "unverified", "uncertain", "cancelled"}:
        return message
    effects = [s for s in history if s.kind == "effect"]
    verified = [s for s in effects if s.status == "succeeded"
                and _object(s.result).get("effect_verified") is True]
    unresolved = [s for s in effects if s.status in {
        "dispatching", "verifying", "succeeded", "uncertain", "failed",
    } and _object(s.result).get("effect_verified") is not True]
    reads = [s for s in history if s.kind == "read" and s.status == "succeeded"
             and not _object(s.document).get("capability_inspection")
             and not _object(s.result).get("failure_category")]
    if not effects and not reads:
        return message
    lines = [message]
    if status == "uncertain" or unresolved:
        lines.append("Eine gestartete Änderung ist noch nicht eindeutig bestätigt. "
                     "Prüfe zuerst den tatsächlichen Zustand; die Änderung nicht wiederholen.")
    elif verified:
        confirmed = ("1 Änderungsschritt ist bestätigt" if len(verified) == 1
                     else f"{len(verified)} Änderungsschritte sind bestätigt")
        lines.append(confirmed + "; "
                     "der gesamte Auftrag ist damit noch nicht abgeschlossen.")
    elif not effects:
        lines.append("Es wurde keine Änderung gestartet.")
    elif effects:
        lines.append("Keine Änderung ist bisher als erfolgreich bestätigt.")

    # The requirement is already tied to the user's goal and target at admission.
    # Never select a source by keywords in a question or by a model's final prose.
    intent = _object(_object(getattr(job, "bindings", {})).get("intent"))
    requirements = intent.get("requirements", [])
    if isinstance(requirements, list) and status != "cancelled":
        targets = {
            r["integration_id"] for r in requirements
            if isinstance(r, dict) and r.get("kind") == "entity_states"
            and r.get("domain") == "update" and isinstance(r.get("integration_id"), str)
        }
        if len(targets) == 1:
            snapshot = states_snapshot(history, next(iter(targets)), "update")
            if snapshot is not None:
                if snapshot["pending"] or not snapshot["unknown"]:
                    count = len(snapshot["pending"])
                    updates = ("1 verfügbares Update" if count == 1
                               else f"{count} verfügbare Updates")
                    lines.append(
                        "Letzte vollständige Abfrage: " + updates + " beobachtet."
                    )
                else:
                    lines.append("Der gelesene Updatebestand enthält unbekannte Zustände; "
                                 "verfügbare Updates sind nicht vollständig bestimmt.")
    if len(lines) == 1 and reads:
        completed = ("1 Datenabfrage wurde abgeschlossen" if len(reads) == 1
                     else f"{len(reads)} Datenabfragen wurden abgeschlossen")
        lines.append(completed + "; "
                     "das angefragte Ergebnis ist noch nicht vollständig belegt.")
    return "\n\n".join(lines)
