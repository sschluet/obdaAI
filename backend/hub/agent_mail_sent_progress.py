"""Inert, schema-bound Sent discovery/query choices for a verified displayed cohort."""

import json
from typing import Any

from hub.action_api import digest, encode
from hub.agent_mail_cohort import current_mail_observations, selected_receipt_rows
from hub.agent_models import AgentJob, AgentStep
from hub.agent_schema import validate
from hub.agent_tools import validate_tool
from hub.mcp_client import schema_digest


def _arguments(name: str, schema: dict[str, Any], folder: str | None) -> dict[str, Any] | None:
    properties, required = schema.get("properties", {}), schema.get("required", [])
    known = (
        {"folder", "limit", "unread_only", "since_days", "sender", "subject", "before"}
        if name == "list_emails"
        else {
            "query",
            "folder",
            "limit",
            "sender",
            "recipient",
            "subject",
            "since_days",
            "before_days",
            "unread_only",
            "has_attachment",
        }
    )
    if (
        schema.get("type") != "object"
        or not isinstance(properties, dict)
        or not isinstance(required, list)
        or not all(isinstance(k, str) for k in required)
        or not set(required) <= set(properties)
    ):
        return None
    if name == "list_folders":
        return {} if not properties and not required else None
    if (
        not set(properties) <= known
        or not {"folder", "limit"} <= set(properties)
        or not isinstance(folder, str)
        or not folder
        or len(folder.encode()) > 512
        or any(c in folder for c in "\x00\r\n")
    ):
        return None
    limit = properties["limit"]
    if not isinstance(limit, dict) or limit.get("type") != "integer":
        return None
    maximum = limit.get("maximum", 100)
    if type(maximum) is not int or maximum < 1:
        return None
    args: dict[str, Any] = {"folder": folder, "limit": min(20, maximum)}
    if name == "search_emails":
        if "query" not in properties:
            return None
        args["query"] = ""
    safe_defaults: dict[str, Any] = {"unread_only": False, "has_attachment": False}
    for key in required:
        if key in args:
            continue
        definition = properties[key]
        if (
            key not in safe_defaults
            or not isinstance(definition, dict)
            or definition.get("default") is not safe_defaults[key]
        ):
            return None
        args[key] = safe_defaults[key]
    return args


def sent_ready_reads(
    db: Any,
    job: AgentJob,
    profiles: dict[str, Any],
    history: list[AgentStep],
    contracts: dict[str, Any],
    *,
    max_bytes: int = 1800,
) -> dict[str, Any]:
    """Offer at most two exact current reads, with no retries, effects or dispatch.

    Querying a discovered Sent folder is an observed bounded attempt, including
    zero results; it never proves that an unmatched original received no reply.
    """
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 4000:
        raise ValueError("Sent read evidence budget is out of bounds")
    cohort = selected_receipt_rows(db, job, profiles)
    result: dict[str, Any] = {
        "decisions": [],
        "decision_sources": [],
        "source_receipts": [],
        "cohort_known": cohort["cohort_known"],
        "coverage_complete": False,
        "untrusted": True,
        "accounts_omitted": 0,
    }
    if not cohort["cohort_known"]:
        return result
    result["cohort_sha256"] = cohort["cohort_sha256"]
    result["source_receipts"] = cohort["source_receipts"]
    observations = current_mail_observations(job, profiles, history)
    accounts = list(dict.fromkeys(r["integration_id"] for r in cohort["rows"]))
    result["accounts_omitted"] = len(accounts)
    for account in accounts:
        profile, rules, _ = profiles[account]
        if profile.kind != "mcp" or not profile.enabled or not rules.enabled:
            continue
        folders = [
            f["name"]
            for f in observations["folders"]
            if f["account_id"] == account
            and f.get("selectable") is True
            and isinstance(f.get("name"), str)
            and isinstance(f.get("flags"), list)
            and "\\Sent" in f["flags"]
        ]
        attempted = {
            q["folder"]
            for q in observations["queries"]
            if q["integration_id"] == account
            and q["sequence"] > observations["discovery_sequences"].get(account, q["sequence"])
        }
        if attempted.intersection(folders):
            continue
        names: tuple[str, ...]
        folder: str | None
        if account not in observations["discovered_accounts"]:
            names, folder = ("list_folders",), None
        elif not folders:
            continue  # Successful discovery without Sent is terminal for this helper.
        else:
            names, folder = ("list_emails", "search_emails"), folders[0]
        interface: dict[str, Any] = next(
            (i for i in contracts.get("interfaces", []) if i.get("integration_id") == account), {}
        )
        for name in names:
            failed = False
            for step in history:
                if (
                    step.job_id != job.id
                    or step.kind != "read"
                    or step.status != "failed"
                    or digest(step.document) != step.sha256
                ):
                    continue
                try:
                    document = json.loads(step.document)
                    if (
                        document.get("integration_id") == account
                        and document.get("tool") == "mcp.call"
                        and document.get("arguments", {}).get("name") == name
                    ):
                        failed = True
                except (ValueError, TypeError):
                    continue
            if failed:
                break
            sha = rules.mcp_read_tools.get(name)
            schema = contracts.get("schemas", {}).get(sha)
            observed = any(
                t.get("name") == name and t.get("schema_sha256") == sha
                for t in interface.get("tools", [])
            )
            if (
                not sha
                or not observed
                or not isinstance(schema, dict)
                or schema_digest(schema) != sha
            ):
                continue
            args = _arguments(name, schema, folder)
            if args is None:
                continue
            call = {"name": name, "schema_sha256": sha, "arguments": args}
            try:
                validate(schema, args)
                normalized, effect = validate_tool(profile.kind, rules, "mcp.call", call)
            except (ValueError, PermissionError):
                continue
            if effect:
                continue
            decision = {
                "kind": "tool",
                "integration_id": account,
                "tool": "mcp.call",
                "arguments": normalized,
                "message": (
                    "Gesendet-Ordner anhand tatsächlicher Ordnermerkmale ermitteln"
                    if name == "list_folders"
                    else "Kopfzeilen im ermittelten Gesendet-Ordner prüfen"
                ),
            }
            candidate = {
                **result,
                "decisions": [*result["decisions"], decision],
                "decision_sources": [
                    *result["decision_sources"],
                    {"integration_id": account, "cohort_sha256": cohort["cohort_sha256"]},
                ],
                "accounts_omitted": result["accounts_omitted"] - 1,
            }
            if len(encode(candidate).encode()) <= max_bytes:
                result = candidate
            break
        if len(result["decisions"]) == 2:
            break
    if len(encode(result).encode()) > max_bytes:
        return {
            "decisions": [],
            "cohort_known": True,
            "reason": "evidence_budget",
            "coverage_complete": False,
            "accounts_omitted": len(accounts),
        }
    return result
