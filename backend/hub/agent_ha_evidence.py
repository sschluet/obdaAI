"""Derived HA state evidence from original, successful current-job read receipts.

This module neither selects tools nor grants authority. Callers supply only the current
job's history after their ordinary target/policy revocation checks.
"""

import html
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from hub.action_api import digest, encode
from hub.agent_failures import read_result_failure

_DOMAIN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ENTITY = re.compile(r"[a-z][a-z0-9_]*\.[a-z0-9_]{1,200}\Z")
_ATTRS = (
    "friendly_name",
    "installed_version",
    "latest_version",
    "in_progress",
    "supported_features",
    "release_url",
    "title",
)


def _get(row: Any, key: str, default: Any = None) -> Any:
    return row.get(key, default) if isinstance(row, Mapping) else getattr(row, key, default)


def _object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, dict) else None


def _scalar(value: Any) -> bool:
    return (
        value is None
        or type(value) in (str, bool, int)
        or (type(value) is float and value == value and abs(value) != float("inf"))
    )


def _row(value: Any, *, projected: bool) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("model_view_only") is True:
        return None
    entity = value.get("/entity_id" if projected else "entity_id")
    state = value.get("/state" if projected else "state")
    if not isinstance(entity, str) or not _ENTITY.fullmatch(entity) or not isinstance(state, str):
        return None
    if not state or len(state) > 200:
        return None
    attributes = value.get("attributes", {})
    if not projected and not isinstance(attributes, dict):
        return None
    result: dict[str, Any] = {"entity_id": entity, "state": state}
    actual = {}
    for key in _ATTRS:
        source = value if projected else attributes
        field = "/attributes/" + key if projected else key
        if field in source and _scalar(source[field]):
            scalar = source[field]
            if not isinstance(scalar, str) or len(scalar) <= 2000:
                actual[key] = scalar
    result["attributes"] = actual
    return result


def _snapshot(
    document: dict[str, Any], result: dict[str, Any], domain: str, require_complete: bool
) -> dict[str, Any] | None:
    if "projection_error" in result or any(
        result.get(key) for key in ("model_view_only", "uncertain", "truncated", "partial")
    ):
        return None
    if result.get("failure_category") or document.get("effect") is True:
        return None
    args, tool = document.get("arguments"), document.get("tool")
    if (
        not isinstance(args, dict)
        or not isinstance(tool, str)
        or (read_result_failure(tool, result) is not None)
    ):
        return None
    projected = False
    complete = True
    if tool == "http":
        if args.get("method") != "GET" or args.get("path") != "/api/states":
            return None
        if args.get("query") or args.get("verification") is not None:
            return None
        body, projection = result.get("body"), args.get("projection")
        if projection is None:
            values = body
        else:
            if (
                not isinstance(projection, dict)
                or not (
                    projection.get("items_path", "") == ""
                    and projection.get("where_pointer") == "/entity_id"
                    and projection.get("where_prefix") == domain + "."
                    and projection.get("where_equals") is None
                    and isinstance(projection.get("fields"), list)
                    and (
                        not projection["fields"]
                        or {"/entity_id", "/state"}.issubset(projection["fields"])
                    )
                )
                or not isinstance(body, dict)
                or body.get("model_view_only")
                or body.get("truncated")
                or body.get("omitted_count", 0) != 0
            ):
                return None
            values = body.get("items")
            matched, returned = body.get("matched"), body.get("returned")
            if (
                not isinstance(values, list)
                or type(matched) is not int
                or (type(returned) is not int or returned != len(values) or matched < returned)
            ):
                return None
            complete = matched == returned
            projected = bool(projection["fields"])
    elif tool == "ha.websocket":
        if args.get("type") != "get_states" or args.get("parameters", {}) != {}:
            return None
        values = result.get("response")
    else:
        return None
    if require_complete and not complete or not isinstance(values, list) or len(values) > 100_000:
        return None
    rows, seen = [], set()
    for value in values:
        row = _row(value, projected=projected)
        if row is None or row["entity_id"] in seen:
            return None
        seen.add(row["entity_id"])
        if row["entity_id"].startswith(domain + "."):
            rows.append(row)
        elif projected:
            return None
    if len(rows) > 1000:
        return None
    return {
        "domain": domain,
        "complete": complete,
        "entities": rows,
        "pending": [r["entity_id"] for r in rows if r["state"] == "on"],
        "current": [r["entity_id"] for r in rows if r["state"] == "off"],
        "unknown": [r["entity_id"] for r in rows if r["state"] not in {"on", "off"}],
        "document_sha256": digest(encode(document)),
        "result_sha256": digest(encode(result)),
    }


def states_snapshot(
    history: Sequence[Any], integration_id: str, domain: str, require_complete: bool = True
) -> dict[str, Any] | None:
    """Return latest qualifying original states receipt, never a model preview."""
    if not _DOMAIN.fullmatch(domain) or not integration_id:
        return None
    candidates = []
    last_effect = max(
        (
            _get(step, "sequence")
            for step in history
            if _get(step, "kind") == "effect"
            and type(_get(step, "sequence")) is int
            and (
                (effect_document := _object(_get(step, "document"))) is None
                or not effect_document.get("integration_id")
                or effect_document.get("integration_id") == integration_id
            )
        ),
        default=0,
    )
    for step in history:
        if _get(step, "kind") != "read" or _get(step, "status") != "succeeded":
            continue
        document, result = _object(_get(step, "document")), _object(_get(step, "result"))
        sequence = _get(step, "sequence")
        if document is None or result is None or document.get("integration_id") != integration_id:
            continue
        if type(sequence) is not int or sequence < 1 or sequence <= last_effect:
            continue
        parsed = _snapshot(document, result, domain, require_complete)
        if parsed is not None:
            candidates.append(
                {
                    **parsed,
                    "sequence": sequence,
                    "integration_id": integration_id,
                    "source": {"tool": document["tool"], "arguments": document["arguments"]},
                }
            )
    return max(candidates, key=lambda item: item["sequence"]) if candidates else None


def evidence_satisfied(
    history: Sequence[Any], integration_id: str, domain: str, require_complete: bool = True
) -> bool:
    return states_snapshot(history, integration_id, domain, require_complete) is not None


def update_state_evidence(document: dict[str, Any], result: dict[str, Any]) -> bool:
    """Compatibility for callers already checking succeeded read kind/status."""
    return _snapshot(document, result, "update", True) is not None


def summary(history: Sequence[Any], integration_id: str, domain: str = "update") -> str | None:
    snapshot = states_snapshot(history, integration_id, domain)
    if snapshot is None or domain != "update":
        return None
    rows = snapshot["entities"]
    pending = [row for row in rows if row["state"] == "on"]
    lines = []
    if pending:
        lines.append(f"Home Assistant meldet {len(pending)} verfügbare Updates:")
        for row in pending[:50]:
            attrs = row["attributes"]
            name = attrs.get("friendly_name")
            label = html.escape(name) if isinstance(name, str) and name else row["entity_id"]
            versions = ""
            if (
                attrs.get("installed_version") is not None
                and attrs.get("latest_version") is not None
            ):
                versions = (
                    " ("
                    + html.escape(str(attrs["installed_version"]))
                    + " → "
                    + (html.escape(str(attrs["latest_version"])) + ")")
                )
            lines.append(f"- {label} (`{row['entity_id']}`){versions}")
        if len(pending) > 50:
            lines.append(f"Weitere {len(pending) - 50} Updates sind verfügbar.")
    elif snapshot["unknown"]:
        lines.append("Verfügbare Updates lassen sich derzeit nicht vollständig bestimmen.")
    else:
        lines.append(
            "Home Assistant meldet aktuell keine verfügbaren Updates."
            if rows
            else "Home Assistant hat keine Update-Statusinformationen gemeldet."
        )
    if snapshot["unknown"]:
        lines.append(
            f"Für {len(snapshot['unknown'])} weitere Komponenten ist gerade kein Status verfügbar."
        )
    return "\n".join(lines)
