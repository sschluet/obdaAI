"""Concrete inert next reads from validated prior mailbox receipt identities.

No goal matching, account selection, query replay, model text interpretation or
execution occurs here. Choices carry their original evidence pointers and need
normal durable dispatch with current permission/schema checks.
"""

import json
from typing import Any

from hub.action_api import encode
from hub.agent_models import AgentJob
from hub.agent_read_references import validated_receipts
from hub.agent_schema import validate
from hub.agent_tools import validate_tool
from hub.mcp_client import schema_digest


def _identity(value: Any) -> str | None:
    return (
        value
        if (
            isinstance(value, str)
            and value
            and len(value.encode()) <= 512
            and not any(c in value for c in "\x00\r\n")
        )
        else None
    )


def _messages(receipt: dict[str, Any]) -> tuple[list[Any], str, dict[str, Any]]:
    response = receipt["result"].get("response")
    if not isinstance(response, dict) or response.get("is_error") or response.get("isError"):
        return [], "", {}
    content = response.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], str):
        return [], "", {}
    try:
        payload = json.loads(content[0])
    except (ValueError, TypeError):
        return [], "", {}
    if receipt["tool"] == "read_email" and isinstance(payload, dict):
        return [payload], "", payload
    if receipt["tool"] == "get_thread" and isinstance(payload, list):
        return payload, "/", {}
    if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        return payload["messages"], "/messages/", payload
    return [], "", {}


def _arguments(name: str, schema: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    properties, required = schema.get("properties"), schema.get("required", [])
    known = (
        {"uid", "message_id", "folder", "max_chars"}
        if name == "read_email"
        else {"uid", "message_id", "folder", "limit"}
    )
    if (
        schema.get("type") != "object"
        or not isinstance(properties, dict)
        or not isinstance(required, list)
        or not all(isinstance(k, str) for k in required)
        or not set(properties) <= known
        or "folder" not in properties
        or not ({"uid", "message_id"} & set(properties))
        or not set(required) <= set(properties)
    ):
        return None
    folder = _identity(row.get("folder"))
    if folder is None:
        return None  # Never substitute a default account or mailbox folder.
    args: dict[str, Any] = {"folder": folder}
    if "uid" in properties:
        if type(row.get("uid")) is not int or row["uid"] < 1:
            return None
        args["uid"] = row["uid"]
    if "message_id" in properties:
        mid = _identity(row.get("message_id"))
        if mid is None:
            return None
        args["message_id"] = mid
    for key in required:
        if key in args:
            continue
        definition = properties[key]
        if not isinstance(definition, dict) or "default" not in definition:
            return None
        default = definition["default"]
        # Known size controls only; never arbitrary default programs/queries.
        if key not in {"max_chars", "limit"} or type(default) is not int or default < 0:
            return None
        args[key] = default
    return args


def ready_reads(
    db: Any,
    job: AgentJob,
    profiles: dict[str, Any],
    contracts: dict[str, Any],
    *,
    max_candidates: int = 2,
    max_bytes: int = 1800,
) -> dict[str, Any]:
    """Offer bounded exact choices from full evidence, never only its first projection.

    Revoked/tampered references raise; unknown schemas yield no candidate. Returned
    decisions are inert. Root execution owns sequencing, budgets and final gates.
    """
    if type(max_candidates) is not int or not 1 <= max_candidates <= 4:
        raise ValueError("Ready mail reads require one to four candidates")
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 4000:
        raise ValueError("Ready mail read evidence budget is out of bounds")
    receipts = validated_receipts(db, job, profiles)
    from hub.agent_mail_cohort import selected_receipt_rows
    from hub.agent_runtime import mail_header_identity

    cohort = selected_receipt_rows(db, job, profiles, receipts)
    displayed = {
        (
            item["integration_id"], item["reference"]["source_job_id"],
            item["reference"]["sequence"], mail_header_identity(item["row"]),
        )
        for item in cohort["rows"]
    } if cohort["cohort_known"] else None
    result: dict[str, Any] = {
        "decisions": [],
        "decision_sources": [],
        "source_receipts": [],
        "source_rows": 0,
        "source_rows_omitted": 0,
        "coverage_complete": False,
        "untrusted": True,
    }
    sources = []
    for receipt in receipts:
        if receipt["tool"] not in {
            "read_email",
            "get_thread",
            "search_emails",
            "list_emails",
            "daily_digest",
        }:
            continue
        rows, prefix, payload = _messages(receipt)
        ref = receipt["reference"]
        indexed_rows = list(enumerate(rows))
        if displayed is not None:
            indexed_rows = [
                (index, row) for index, row in indexed_rows if isinstance(row, dict) and (
                    ref["integration_id"], ref["source_job_id"], ref["sequence"],
                    mail_header_identity(row),
                ) in displayed
            ]
        rows = [row for _, row in indexed_rows]
        index = len(result["source_receipts"])
        result["source_receipts"].append(
            {
                "source_id": f"agent-read:{ref['source_job_id']}:{ref['sequence']}",
                "integration_id": ref["integration_id"],
                "result_sha256": ref["result_sha256"],
                "document_sha256": ref["document_sha256"],
                "returned_count": len(rows),
                "more_pages": bool(payload.get("next_cursor")),
                "upstream_truncated": payload.get("truncated") is True,
            }
        )
        result["source_rows"] += len(rows)
        sources.append((index, ref["integration_id"], indexed_rows, prefix))
    result["source_rows_omitted"] = result["source_rows"]
    attempts = 0
    seen = set()
    for source_index, identifier, indexed_rows, prefix in sources:
        if identifier not in profiles:
            raise PermissionError("Prior mailbox target is no longer selected")
        profile, rules, _ = profiles[identifier]
        if profile.kind != "mcp" or not rules.enabled:
            continue
        interface: dict[str, Any] = next(
            (
                item
                for item in contracts.get("interfaces", [])
                if item.get("integration_id") == identifier
            ),
            {},
        )
        for row_index, row in indexed_rows[:100]:
            if not isinstance(row, dict):
                continue
            for name in ("read_email", "get_thread"):
                sha = rules.mcp_read_tools.get(name)
                observed = next(
                    (
                        tool
                        for tool in interface.get("tools", [])
                        if tool.get("name") == name and tool.get("schema_sha256") == sha
                    ),
                    None,
                )
                schema = contracts.get("schemas", {}).get(sha)
                if (
                    not sha
                    or not observed
                    or not isinstance(schema, dict)
                    or schema_digest(schema) != sha
                ):
                    continue
                args = _arguments(name, schema, row)
                if args is None:
                    continue
                key = (identifier, name, encode(args))
                if key in seen:
                    break
                attempts += 1
                if attempts > max_candidates * 4:
                    return result
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
                    "integration_id": identifier,
                    "tool": "mcp.call",
                    "arguments": normalized,
                    "message": "Nachricht anhand des gespeicherten Belegs lesen",
                }
                provenance = {
                    "source_index": source_index,
                    "pointer": prefix + str(row_index) if prefix else "",
                }
                result["decisions"].append(decision)
                result["decision_sources"].append(provenance)
                result["source_rows_omitted"] -= 1
                if len(encode(result).encode()) > max_bytes:
                    result["decisions"].pop()
                    result["decision_sources"].pop()
                    result["source_rows_omitted"] += 1
                    continue  # A later actual identity may fit without truncation.
                seen.add(key)
                if len(result["decisions"]) >= max_candidates:
                    return result
                break
    return result
