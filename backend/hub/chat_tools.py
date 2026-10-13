"""One fixed read selected locally; no model arguments, URLs or write operations."""

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import TOOLS, digest, encode, lock
from hub.budgets import ExecutionLimitError
from hub.config import Settings
from hub.db import ActionIntent, ActionReceipt, Project, Source
from hub.ha_backups import inspect as backups
from hub.ha_maintenance import inspect as maintenance
from hub.home_assistant import inspect as health

READS = {"hub.inspect", "ha.inspect", "ha.backups.inspect", "ha.maintenance.plan"}


def read(
    factory: sessionmaker[Session], cfg: Settings, run_id: str, tool_id: str
) -> dict[str, Any]:
    if tool_id not in READS:
        raise ExecutionLimitError("Kein freigegebenes Chat-Lesewerkzeug")
    try:
        with factory() as db:
            policy = lock(db)
            row = db.scalar(select(ActionIntent).where(ActionIntent.request_key == run_id))
            if row:
                if (
                    row.tool_id != tool_id
                    or row.parameters != "{}"
                    or row.tool_revision != TOOLS[tool_id]["revision"]
                ):
                    raise ExecutionLimitError("Chat-Lesevorgabe geändert")
                if row.status == "revoked":
                    raise ExecutionLimitError("Chat-Lesevorschlag widerrufen")
                receipt = db.get(ActionReceipt, row.id)
                if receipt:
                    return {
                        "action_id": row.id,
                        "tool_id": tool_id,
                        "result": json.loads(receipt.result),
                    }
            else:
                row = ActionIntent(
                    request_key=run_id,
                    tool_id=tool_id,
                    tool_revision=TOOLS[tool_id]["revision"],
                    parameters="{}",
                    parameters_sha256=digest("{}"),
                    label="LOCAL_ONLY",
                    policy_revision=policy.revision,
                )
                db.add(row)
                db.flush()
            # Same fixed read boundary as the authenticated gateway, serialized with revoke.
            if tool_id == "hub.inspect":
                result = {
                    "projects": db.scalar(select(func.count()).select_from(Project)),
                    "sources": db.scalar(select(func.count()).select_from(Source)),
                    "label": "LOCAL_ONLY",
                }
            else:
                result = {
                    "ha.inspect": health,
                    "ha.backups.inspect": backups,
                    "ha.maintenance.plan": maintenance,
                }[tool_id](cfg)
            db.add(ActionReceipt(action_id=row.id, result=encode(result)))
            row.status = "succeeded"
            db.commit()
            return {"action_id": row.id, "tool_id": tool_id, "result": result}
    except HTTPException:
        raise ExecutionLimitError(
            "Keine aktuelle Systemprüfung: Lesezugang nicht verfügbar; kein Wartungseingriff"
        ) from None


def context_result(report: dict[str, Any]) -> dict[str, Any]:
    """Bounded summary only; complete read receipt stays in the gateway."""
    row: dict[str, Any] = report["result"]
    tool = report["tool_id"]
    if tool == "hub.inspect":
        return row
    if tool == "ha.inspect":
        return {
            k: row.get(k)
            for k in (
                "checked_at",
                "version",
                "installation_type",
                "supervisor_present",
                "available_updates",
                "unavailable_updates",
                "writes_enabled",
            )
        } | {"updates": row.get("updates", [])[:20]}
    if tool == "ha.backups.inspect":
        return {
            k: row.get(k)
            for k in (
                "checked_at",
                "operating_system",
                "core_version",
                "supervisor_healthy",
                "backup_state",
                "backup_count",
                "agent_error_count",
                "last_completed_automatic_backup",
                "restore_verified",
                "archive_integrity_verified",
                "recovery_key_verified",
                "writes_enabled",
            )
        }
    return {
        k: row.get(k)
        for k in (
            "checked_at",
            "profile",
            "writes_enabled",
            "restore_verified",
            "blockers",
            "steps",
            "executed_changes",
        )
    } | {"updates": row.get("updates", [])[:20]}
