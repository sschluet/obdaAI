"""Human-configured operation prerequisites: original same-job verified receipts only."""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from hub.action_api import digest, encode
from hub.agent_tools import HTTPEffectOperation, Rules, validate_tool


def validate_policy(kind: str, rules: Rules) -> None:
    """Validate feasibility, never enable an operation that current rules prohibit."""
    enabled = rules.model_copy(update={"enabled": True})
    for prerequisite in rules.effect_prerequisites:
        for operation in (prerequisite.operation, prerequisite.requires):
            try:
                _, effect = validate_tool(
                    kind,
                    enabled,
                    operation.tool,
                    {
                        "method": operation.method,
                        "path": operation.path,
                    },
                )
            except (ValueError, PermissionError):
                raise ValueError(
                    "Voraussetzungen benötigen bereits erlaubte HTTP-Änderungen"
                ) from None
            if not effect:
                raise ValueError("Voraussetzungen müssen echte Änderungen betreffen")


def _object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _original(step: Any) -> dict[str, Any] | None:
    document = _object(getattr(step, "document", None))
    if not document or digest(encode(document)) != getattr(step, "sha256", None):
        return None
    return document


def _matches(operation: HTTPEffectOperation, tool: str, args: Mapping[str, Any]) -> bool:
    # Comparison only: an already validated HA service call is the same logical
    # service via another transport. Never rewrite its arguments or grant HTTP/WS.
    if tool == "ha.websocket" and args.get("type") == "call_service":
        parameters = _object(args.get("parameters"))
        domain, service = parameters.get("domain"), parameters.get("service")
        if all(
            isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
            for value in (domain, service)
        ):
            return (
                operation.method == "POST" and operation.path == f"/api/services/{domain}/{service}"
            )
    return (
        tool == operation.tool
        and args.get("method") == operation.method
        and args.get("path") == operation.path
    )


def _proof(
    history: Sequence[Any],
    identifier: str,
    operation: HTTPEffectOperation,
    *,
    job_id: str | None,
) -> int | None:
    for effect in reversed(history):
        document = _original(effect)
        result = _object(getattr(effect, "result", None))
        if (
            not document
            or effect.kind != "effect"
            or effect.status != "succeeded"
            or result.get("effect_verified") is not True
            or not getattr(effect, "job_id", None)
            or job_id is not None
            and effect.job_id != job_id
            or document.get("integration_id") != identifier
            or not _matches(operation, document.get("tool", ""), _object(document.get("arguments")))
        ):
            continue
        sequence = result.get("verification_step")
        if type(sequence) is not int or sequence <= effect.sequence:
            continue
        verification = next(
            (
                item
                for item in history
                if item.sequence == sequence and getattr(item, "job_id", None) == effect.job_id
            ),
            None,
        )
        proof_document = _original(verification) if verification else None
        proof = _object(getattr(verification, "result", None))
        if verification is None or not proof_document or verification.status != "succeeded":
            continue
        if (
            verification.kind == "verification"
            and type(proof_document.get("effect_step")) is int
            and proof_document["effect_step"] == effect.sequence
            and encode(proof_document.get("predicate"))
            == encode(document["arguments"].get("verification"))
            and isinstance(proof_document.get("predicate"), dict)
            and proof.get("effect_verified") is True
        ):
            return int(effect.sequence)
        if (
            verification.kind == "read"
            and proof_document.get("tool") == "http.verify"
            and proof_document.get("integration_id") == identifier
            and type(_object(proof_document.get("arguments")).get("effect_step")) is int
            and _object(proof_document.get("arguments"))["effect_step"] == effect.sequence
            and proof.get("verification_passed") is True
        ):
            return int(effect.sequence)
    return None


def missing(
    history: Sequence[Any],
    identifier: str,
    rules: Rules,
    tool: str,
    arguments: Mapping[str, Any],
    *,
    job_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return operator-owned required operations; no execution, argument inference or grants."""
    return [
        prerequisite.requires.model_dump()
        for prerequisite in rules.effect_prerequisites
        if _matches(prerequisite.operation, tool, arguments)
        and _proof(history, identifier, prerequisite.requires, job_id=job_id) is None
    ]


def backup_observability(
    history: Sequence[Any], identifier: str, rules: Rules, tool: str,
    arguments: Mapping[str, Any], *, job_id: str, kind: str,
) -> dict[str, Any] | None:
    """Require observed existing proof fields only for configured HA backup prerequisites.

    This is a precondition, never a replacement for independent post-effect proof.
    No read is dispatched, no field or expected value is inferred.
    """
    if kind != "home_assistant" or not any(
        prerequisite.requires.path in {
            "/api/services/backup/create", "/api/services/backup/create_automatic",
        }
        and _matches(prerequisite.requires, tool, arguments)
        for prerequisite in rules.effect_prerequisites
    ):
        return None
    verification = _object(arguments.get("verification"))
    path, query = verification.get("path"), verification.get("query", {})
    expected = verification.get("expected")
    issue: dict[str, Any] = {
        "type": "backup_verification_observation_required",
        "next_action": "Before creating the configured backup, read its proposed "
        "verification resource and observe every expected field. Use a real readable "
        "status resource, never a service-execution GET. Do not invent fields or values. "
        "The postcondition must differ from the observed state; no change was sent.",
    }
    if not isinstance(path, str) or not isinstance(expected, dict) or not expected:
        return issue
    issue["required_read"] = {"tool": "http", "method": "GET", "path": path, "query": query}
    last_effect = max((item.sequence for item in history
                       if item.kind == "effect" and (
                           _object(getattr(item, "document", None)).get("integration_id")
                           == identifier)), default=-1)
    # Choose the latest exact resource read; never revive older evidence past a
    # failed/tampered matching read or an intervening target mutation.
    candidate = None
    for item in history:
        document = _object(getattr(item, "document", None))
        args = _object(document.get("arguments"))
        if (item.kind == "read" and document.get("integration_id") == identifier
                and document.get("tool") == "http" and args.get("method") == "GET"
                and args.get("path") == path
                and encode(args.get("query", {})) == encode(query)):
            if candidate is None or item.sequence > candidate.sequence:
                candidate = item
    if candidate is None or candidate.sequence <= last_effect:
        return issue
    original_document = _original(candidate)
    result = _object(getattr(candidate, "result", None))
    status = result.get("http_status")
    if (not original_document or getattr(candidate, "job_id", None) != job_id
            or candidate.status != "succeeded" or type(status) is not int
            or not 200 <= status < 300 or result.get("projection_error")
            or result.get("model_view_only") or result.get("effect_uncertain")
            or _object(original_document.get("arguments")).get("projection") is not None):
        return issue
    already_true = True
    for pointer, wanted in expected.items():
        value: Any = result
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            return issue
        try:
            for key in pointer[1:].split("/"):
                key = key.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) else value[key]
        except (KeyError, IndexError, TypeError, ValueError):
            return issue
        if type(value) is not type(wanted):
            return issue
        # Match the existing verifier exactly: its top-level JSON type check
        # precedes Python equality (including nested numeric/bool equality).
        already_true = already_true and value == wanted
    if already_true:
        return {"type": "backup_verification_already_true",
                "next_action": "The proposed static backup postcondition is already true "
                "before creation and cannot prove a new backup. Choose an observable, "
                "supported changing proof, or stop without sending the backup."}
    return None


def check(
    history: Sequence[Any],
    identifier: str,
    rules: Rules,
    tool: str,
    arguments: Mapping[str, Any],
    *,
    job_id: str,
    kind: str = "",
) -> None:
    if backup_observability(
        history, identifier, rules, tool, arguments, job_id=job_id, kind=kind,
    ):
        raise PermissionError("Backup-Verifikation benötigt zuvor beobachtbare neue Statusbelege")
    if missing(history, identifier, rules, tool, arguments, job_id=job_id):
        raise PermissionError("Eine konfigurierte Aktionsvoraussetzung ist noch nicht verifiziert")


def planning_context(
    history: Sequence[Any],
    profiles: Mapping[str, Any],
    *,
    job_id: str,
) -> list[dict[str, Any]]:
    rows = []
    for identifier, (profile, rules, _config) in profiles.items():
        for prerequisite in rules.effect_prerequisites:
            proof = _proof(history, identifier, prerequisite.requires, job_id=job_id)
            try:
                validate_policy(profile.kind, rules)
                available = (
                    profile.writes_enabled is True
                    and profile.enabled is True
                    and rules.enabled
                    and rules.max_effects > 0
                )
            except ValueError:
                available = False
            rows.append(
                {
                    "integration_id": identifier,
                    **prerequisite.model_dump(),
                    "satisfied": proof is not None,
                    "receipt_sequence": proof,
                    "permission_available": available,
                }
            )
    return rows
