"""Fixed light-entity inventory reads and factual rendering, without model or dispatch."""

import html
import re
from collections.abc import Mapping, Sequence
from typing import Any

from hub.action_api import digest, encode
from hub.agent_failures import read_result_failure

_LIMIT = 100
_FIELDS = ["/entity_id", "/state", "/attributes/friendly_name"]
_ENTITY = re.compile(r"light\.[a-z0-9_]{1,200}\Z")
_STATES = {"on": "an", "off": "aus", "unknown": "unbekannt", "unavailable": "nicht verfügbar"}
_LIGHTS = r"(?:lampen|leuchten|licht-entitäten|lichter|lights|light entities)"
_HA = r"(?:home\s?assistant|ha)"
_LOCATION = rf"(?:in\s+(?:(?:meinem|unserem)\s+)?{_HA})"
_INVENTORY = [
    rf"welche\s+{_LIGHTS}\s+habe\s+ich(?:\s+{_LOCATION})?",
    rf"welche\s+{_LIGHTS}\s+sind\s+{_LOCATION}\s+(?:vorhanden|verfügbar)",
    rf"(?:zeige|zeig|liste)\s+(?:mir\s+)?(?:meine|unsere)\s+{_LIGHTS}",
    rf"(?:which|what)\s+{_LIGHTS}\s+do\s+i\s+have(?:\s+in\s+(?:my\s+)?{_HA})?",
    rf"(?:list|show)\s+(?:me\s+)?(?:my|our)\s+{_LIGHTS}",
]
_ON = [
    rf"welche\s+(?:meiner|unserer)\s+{_LIGHTS}\s+sind\s+an",
    rf"which\s+of\s+(?:my|our)\s+{_LIGHTS}\s+are\s+on",
]
_FOLLOWUP = [
    r"welche\s+davon\s+sind\s+an", r"welche\s+der\s+(?:lampen|leuchten)\s+sind\s+an",
    r"which\s+of\s+(?:those|these|them)\s+are\s+on",
]


def _intent(goal: str) -> tuple[bool, bool] | None:
    if not isinstance(goal, str) or len(goal) > 500 or any(ord(c) < 32 for c in goal):
        return None
    text = " ".join(goal.casefold().split())
    text = re.sub(r"^(?:bitte|please)\s+", "", text)
    for patterns, result in ((_INVENTORY, (False, False)), (_ON, (True, False)),
                             (_FOLLOWUP, (True, True))):
        if any(re.fullmatch(pattern + r"\s*[?.!]?", text) for pattern in patterns):
            return result
    return None


def _arguments() -> dict[str, Any]:
    return {"method": "GET", "path": "/api/states", "projection": {
        "items_path": "", "where_pointer": "/entity_id", "where_prefix": "light.",
        "fields": list(_FIELDS), "limit": _LIMIT,
    }}



def _valid_plan(selected: Any) -> bool:
    from hub.agent_tools import HTTPCall

    if not isinstance(selected, Mapping) or not (
        type(selected.get("version")) is int and selected["version"] == 1
        and isinstance(selected.get("integration_id"), str) and selected["integration_id"]
        and selected.get("tool") == "http" and selected.get("domain") == "light"
        and selected.get("mode") in {"inventory", "on_cohort"}
        and type(selected.get("only_on")) is bool
        and selected.get("arguments") == HTTPCall.model_validate(_arguments()).model_dump()
    ):
        return False
    cohort, refs = selected.get("cohort"), selected.get("source_references")
    if selected["mode"] == "inventory":
        return cohort is None and refs == []
    return bool(
        selected["only_on"] and isinstance(cohort, list) and len(cohort) <= _LIMIT
        and all(isinstance(entity, str) and _ENTITY.fullmatch(entity) for entity in cohort)
        and len(set(cohort)) == len(cohort) and isinstance(refs, list) and len(refs) == 1
        and isinstance(refs[0], dict) and set(refs[0]) == {
            "source_job_id", "sequence", "document_sha256", "result_sha256"
        }
        and isinstance(refs[0]["source_job_id"], str) and refs[0]["source_job_id"]
        and type(refs[0]["sequence"]) is int and refs[0]["sequence"] > 0
        and all(isinstance(refs[0][key], str) and re.fullmatch(r"[a-f0-9]{64}", refs[0][key])
                for key in ("document_sha256", "result_sha256"))
    )


def _rows(receipt: Any, limit: int = _LIMIT) -> tuple[list[dict[str, Any]], int] | None:
    if not isinstance(receipt, dict) or read_result_failure("http", receipt) is not None:
        return None
    body = receipt.get("body")
    if not isinstance(body, dict):
        return None
    items, matched, returned = body.get("items"), body.get("matched"), body.get("returned")
    if (
        not isinstance(items, list) or type(matched) is not int or not 0 <= matched <= 100_000
        or type(returned) is not int or returned != len(items) or returned != min(matched, limit)
    ):
        return None
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != set(_FIELDS):
            return None
        entity, state, name = (item[field] for field in _FIELDS)
        if (
            not isinstance(entity, str) or not _ENTITY.fullmatch(entity) or entity in seen
            or not isinstance(state, str) or state not in _STATES
            or name is not None and not isinstance(name, str)
        ):
            return None
        seen.add(entity)
    return items, matched


def _source_cohort(
    source_refs: Sequence[Mapping[str, Any]], identifier: str, profile: Any
) -> tuple[list[str], list[dict[str, Any]]] | None:
    candidates = []
    for source in source_refs:
        if not isinstance(source, Mapping):
            continue
        ref, document, receipt = (source.get(key) for key in ("reference", "document", "result"))
        if not all(isinstance(value, dict) for value in (ref, document, receipt)):
            continue
        assert isinstance(ref, dict) and isinstance(document, dict) and isinstance(receipt, dict)
        arguments = document.get("arguments", {})
        if not isinstance(arguments, dict):
            continue
        projection = arguments.get("projection")
        if not (
            source.get("tool") == document.get("tool") == "http"
            and document.get("integration_id") == ref.get("integration_id") == identifier
            and arguments.get("method") == "GET" and arguments.get("path") == "/api/states"
            and isinstance(projection, dict) and projection.get("items_path") == ""
            and projection.get("where_pointer") == "/entity_id"
            and projection.get("where_prefix") == "light."
            and projection.get("fields") == _FIELDS
            and type(projection.get("limit")) is int and 1 <= projection["limit"] <= _LIMIT
            and ref.get("version") == 1 and type(ref.get("sequence")) is int
            and ref["sequence"] > 0 and isinstance(ref.get("source_job_id"), str)
            and bool(ref["source_job_id"])
            and ref.get("document_sha256") == digest(encode(document))
            and ref.get("result_sha256") == digest(encode(receipt))
            and ref.get("profile_revision") == profile.revision
            and ref.get("config_sha256") == digest(profile.config)
        ):
            continue
        parsed = _rows(receipt, projection["limit"])
        if parsed is None:
            continue
        pointer = {key: ref[key] for key in (
            "source_job_id", "sequence", "document_sha256", "result_sha256"
        )}
        rows = parsed[0]
        if "inventory_plan" in document:
            previous = document["inventory_plan"]
            if not _valid_plan(previous) or previous["integration_id"] != identifier or (
                previous["arguments"] != arguments
            ):
                continue
            if previous["mode"] == "on_cohort":
                rows = [row for row in rows if row["/entity_id"] in previous["cohort"]]
            if previous["only_on"]:
                rows = [row for row in rows if row["/state"] == "on"]
        candidates.append((ref["source_job_id"], ref["sequence"], rows, pointer))
    if not candidates or len({candidate[0] for candidate in candidates}) != 1:
        return None  # Different source jobs need the ordinary contextual planner.
    _, _, rows, pointer = max(candidates, key=lambda candidate: candidate[1])
    return sorted(row["/entity_id"] for row in rows), [pointer]


def plan(
    goal: str, profiles: Mapping[str, Any], source_refs: Sequence[Mapping[str, Any]] | None = None,
    *, request_intent: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Inert request only. Sources must come from freshly validated same-chat receipts.

    The caller owns conversation provenance, durable intents, budgets and current
    final-boundary permission checks. This function never grants authority.
    """
    from hub.agent_tools import validate_tool

    intent = _intent(goal)
    if request_intent is not None:
        from hub.agent_intent import RequestIntent

        semantic = RequestIntent.model_validate(request_intent)
        requirements = semantic.requirements
        if (
            semantic.read_only and semantic.answer_kind in {"light_inventory", "light_on_cohort"}
            and len(semantic.target_ids) == 1 and semantic.target_ids[0] in profiles
            and len(requirements) == 1 and requirements[0].kind == "entity_states"
            and requirements[0].domain == "light"
            and requirements[0].integration_id == semantic.target_ids[0]
        ):
            intent = (semantic.answer_kind == "light_on_cohort", semantic.followup)
        else:
            return None
    targets = [(identifier, values) for identifier, values in profiles.items()
               if values[0].kind == "home_assistant"]
    if intent is None or len(targets) != 1:
        return None
    identifier, (profile, rules, _) = targets[0]
    if not profile.enabled or not rules.enabled:
        return None
    try:
        arguments, effect = validate_tool(profile.kind, rules, "http", _arguments())
    except (PermissionError, ValueError):
        return None
    if effect:
        return None
    only_on, followup = intent
    cohort: list[str] | None = None
    references: list[dict[str, Any]] = []
    if followup:
        source = _source_cohort(source_refs or [], identifier, profile)
        if source is None:
            return None
        cohort, references = source
    return {"version": 1, "integration_id": identifier, "tool": "http", "arguments": arguments,
            "domain": "light", "mode": "on_cohort" if followup else "inventory",
            "only_on": only_on, "cohort": cohort, "source_references": references}


def _display(value: str) -> str:
    value = " ".join("".join(c if c.isprintable() else " " for c in value).split())[:80]
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~=-])", r"\\\1", html.escape(value, quote=False))


def summary(receipt: Any, selected: Mapping[str, Any]) -> str | None:
    """Render actual bounded entity observations, never infer missing states or devices."""
    if not _valid_plan(selected):
        return None
    parsed = _rows(receipt)
    if parsed is None:
        return None
    rows, matched = parsed
    cohort = selected.get("cohort")
    if selected["mode"] == "on_cohort":
        if not (
            selected["only_on"] and isinstance(cohort, list) and len(cohort) <= _LIMIT
            and all(isinstance(entity, str) and _ENTITY.fullmatch(entity) for entity in cohort)
            and len(set(cohort)) == len(cohort) and selected.get("source_references")
        ):
            return None
        found = {row["/entity_id"] for row in rows}
        missing = sorted(set(cohort) - found)
        rows = [row for row in rows if row["/entity_id"] in cohort]
        lines = [f"Von {len(cohort)} zuvor abgerufenen Licht-Entitäten wurden "
                 f"{len(rows)} im aktuellen Ausschnitt wiedergefunden."]
    else:
        if cohort is not None:
            return None
        missing = []
        lines = [f"Beobachtet: {matched} Licht-Entitäten; "
                 f"im abgerufenen Ausschnitt: {len(rows)}."]
    selected_rows = [row for row in rows if not selected["only_on"] or row["/state"] == "on"]
    if selected["only_on"]:
        lines.append(f"Davon aktuell an: {len(selected_rows)}.")
    if selected_rows:
        for row in sorted(selected_rows, key=lambda item: item["/entity_id"]):
            entity, state, name = (row[field] for field in _FIELDS)
            lines.append(f"- {_display(name or entity)} (`{entity}`): {_STATES[state]}.")
    elif not selected["only_on"]:
        lines.append("Im abgerufenen Ausschnitt wurden keine Licht-Entitäten gefunden.")
    unknown = sum(row["/state"] in {"unknown", "unavailable"} for row in rows)
    if unknown:
        lines.append(f"Unbekannt oder nicht verfügbar: {unknown}; nicht als ausgeschaltet gezählt.")
    if missing:
        lines.append(f"Im aktuellen Ausschnitt nicht beobachtet: {len(missing)} "
                     "(daraus folgt nicht, dass sie ausgeschaltet oder entfernt sind).")
        lines.extend(f"- `{entity}`: nicht beobachtet." for entity in missing)
    returned = receipt["body"]["returned"]
    if matched > returned:
        lines.append(f"Begrenzter Ausschnitt: {returned} von {matched} Licht-Entitäten abgerufen "
                     f"(Limit {_LIMIT}).")
    lines.append("Die Anzahl beschreibt Licht-Entitäten, keine Anzahl physischer Geräte.")
    answer = "\n".join(lines)
    return answer if len(answer) <= 80_000 else None
