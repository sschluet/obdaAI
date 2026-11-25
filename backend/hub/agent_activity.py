"""Receipt-derived activity for people, never model reasoning or invented progress."""

import json
import time
from collections.abc import Sequence
from typing import Any

_ACTIVE = {"queued", "running", "awaiting_approval", "awaiting_input"}
_WORK = {"read", "research", "effect", "verification"}
_KINDS = {
    "read": "Verbindung und Daten prüfen",
    "research": "Öffentliche Informationen recherchieren",
    "effect": "Änderung ausführen",
    "verification": "Ergebnis prüfen",
    "feedback": "Werkzeugaufruf anpassen",
    "input": "Deine Antwort übernehmen",
}
_PHASES = {
    "read": "reading", "research": "researching", "effect": "changing",
    "verification": "verifying", "feedback": "recovering",
}


def _document(step: Any) -> dict[str, Any]:
    try:
        value = json.loads(step.document)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def activity(job: Any, steps: Sequence[Any], *, model_run: Any = None,
             now: float | None = None) -> dict[str, Any]:
    """Only fixed copy and existing timestamps/statuses cross this UI boundary.

    Counts describe recorded tool steps, not a forecast of how much work remains.
    A queued or slow model does not imply any target operation has started.
    """
    now = time.time() if now is None else now
    last = steps[-1] if steps else None
    document = _document(last) if last else {}
    status = job.status
    phase, message = "planning", "Nächsten Schritt vorbereiten"
    waiting, next_action = "", ""
    if status == "queued":
        phase, message = "queued", "Auftrag angenommen"
        waiting = "Wartet auf die Ausführung."
    elif status == "awaiting_approval":
        phase, message = "approval", "Eine Änderung braucht deine Freigabe"
        next_action = "Prüfe den vorgesehenen Schritt und gib ihn frei oder brich ab."
    elif status == "awaiting_input":
        phase, message = "input", "Deine Antwort wird benötigt"
        next_action = "Beantworte die Rückfrage im Chat."
    elif status in {"succeeded", "observed"}:
        phase = "completed"
        message = "Ergebnis geprüft" if status == "succeeded" else "Abfrage abgeschlossen"
    elif status == "cancelled":
        phase, message = "cancelled", "Auftrag abgebrochen"
        if any(s.kind == "effect" and s.status in {"dispatching", "uncertain"} for s in steps):
            next_action = "Bereits gestartete Änderungen können noch laufen. Zustand erst prüfen."
    elif status in {"uncertain", "unverified"}:
        phase, message = "uncertain", "Das Ergebnis ist noch nicht vollständig bestätigt"
        next_action = "Prüfe zuerst den tatsächlichen Zustand. Änderungen nicht erneut starten."
    elif status == "failed":
        phase, message = "failed", "Der Auftrag konnte nicht abgeschlossen werden"
        if any(s.kind == "effect" for s in steps):
            next_action = "Prüfe die bisherigen Änderungen vor einem weiteren Auftrag."
        else:
            next_action = "Die Anfrage kann mit erhaltenen Belegen erneut vorbereitet werden."
    elif job.cancel_requested:
        phase, message = "cancelled", "Abbruch angefordert"
        waiting = "Der bereits gestartete Schritt wird noch abgeglichen."
    elif last is not None:
        if last.kind == "model":
            if document.get("intent_interpretation") is True:
                message = "Anfrage und passende Verbindungen zuordnen"
            elif document.get("summarize_only") is True:
                message = "Antwort aus den gelesenen Ergebnissen zusammenstellen"
            else:
                message = "Passenden nächsten Schritt auswählen"
            if model_run is not None and model_run.status == "queued":
                waiting = "Wartet auf das lokale Modell."
            elif last.status in {"prepared", "dispatching"}:
                waiting = "Das lokale Modell verarbeitet die Anfrage."
        elif last.status in {"prepared", "dispatching", "verifying"}:
            phase = "verifying" if last.status == "verifying" else _PHASES.get(
                last.kind, "planning"
            )
            message = "Ergebnis prüfen" if phase == "verifying" else _KINDS.get(
                last.kind, "Nächsten Schritt vorbereiten"
            )
            if last.status == "prepared":
                message = {
                    "read": "Datenabruf vorbereiten",
                    "effect": "Änderung vorbereiten",
                    "verification": "Ergebnisprüfung vorbereiten",
                }.get(last.kind, message)
        elif last.kind == "feedback":
            phase, message = "recovering", "Werkzeugaufruf intern anpassen"
        elif last.kind in _WORK and last.status == "succeeded":
            message = "Ergebnis liegt vor · nächsten Schritt vorbereiten"

    work = [s for s in steps if s.kind in _WORK]
    timestamps = [job.created, *[s.created for s in steps]]
    if job.finished is not None:
        timestamps.append(job.finished)
    if model_run is not None and model_run.finished is not None:
        timestamps.append(model_run.finished)
    finished = job.finished if job.finished is not None else now
    return {
        "phase": phase,
        "message": message,
        "updated_at": max(timestamps),
        "elapsed_seconds": max(0, int(finished - job.created)),
        "waiting_reason": waiting,
        "next_action": next_action,
        "can_cancel": status in _ACTIVE and not job.cancel_requested,
        "completed_steps": sum(s.status == "succeeded" for s in work),
        "total_steps": len(work),
        "event_key": ":".join(str(value) for value in (
            job.id, status, last.sequence if last else 0, last.status if last else "",
            getattr(model_run, "status", ""), bool(job.cancel_requested),
        )),
        "timeline": [
            {"sequence": s.sequence, "kind": s.kind, "status": s.status,
             "message": _KINDS[s.kind]}
            for s in steps if s.kind in _KINDS
        ][-6:],
    }
