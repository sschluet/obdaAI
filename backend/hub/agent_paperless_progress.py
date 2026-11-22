"""Inert document choices from full, currently authorized archive receipts.

No model prose, remote requests, new grants or automatic retries. The shared agent
still owns its fresh gate, native grammar, durable intent and final dispatch.
"""

import json
from typing import Any

from hub.action_api import digest, encode
from hub.agent_document_intent import bound_content_reference
from hub.agent_document_intent import selection as _selection
from hub.agent_models import AgentJob, AgentStep
from hub.agent_read_references import _paperless, validated_receipts
from hub.agent_tools import validate_tool
from hub.db import Message


def _attempted(
    job: AgentJob,
    profiles: dict[str, Any],
    history: list[AgentStep],
    account: str,
    identifier: int,
) -> bool:
    """Suppress both completed reads and failed/uncertain attempts, never replay."""
    profile, rules, config = profiles[account]
    binding = next(b for b in json.loads(job.bindings)["profiles"] if b["id"] == account)
    for step in history:
        if (
            step.job_id != job.id
            or step.kind != "read"
            or step.status not in {"succeeded", "failed", "uncertain"}
            or digest(step.document) != step.sha256
        ):
            continue
        try:
            document = json.loads(step.document)
            if (
                document.get("tool") != "paperless.read"
                or document.get("integration_id") != account
            ):
                continue
            args, effect = validate_tool(
                profile.kind, rules, document["tool"], document["arguments"]
            )
            target = document["target"]
            if (
                effect
                or args["operation"] != "document"
                or args["document_id"] != identifier
                or target.get("kind") != profile.kind
                or target.get("url") != config.get("url")
                or target.get("profile_revision") != profile.revision
                or target.get("config_sha256") != digest(profile.config)
                or target.get("policy_revision", binding["policy_revision"])
                != binding["policy_revision"]
            ):
                continue
            if step.status in {"failed", "uncertain"}:
                return True
            _paperless({**document, "arguments": args}, json.loads(step.result))
            return True
        except (KeyError, TypeError, ValueError, PermissionError):
            continue
    return False


def ready_reads(
    db: Any,
    job: AgentJob,
    profiles: dict[str, Any],
    history: list[AgentStep],
    *,
    max_candidates: int = 2,
    max_bytes: int = 1800,
) -> dict[str, Any]:
    """Resolve an observed ID/ordinal into one exact authorized document read.

    Revoked evidence raises. Unknown selection, account ambiguity, empty/out of
    range results or a previous matching attempt produces no concrete choice.
    The latest bound search supplies its actual returned order, never prose order.
    """
    if type(max_candidates) is not int or not 1 <= max_candidates <= 4:
        raise ValueError("Ready archive reads require one to four candidates")
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 4000:
        raise ValueError("Ready archive evidence budget is out of bounds")
    receipts = validated_receipts(db, job, profiles)
    result: dict[str, Any] = {
        "decisions": [],
        "decision_sources": [],
        "source_receipts": [],
        "source_rows": 0,
        "source_rows_omitted": 0,
        "coverage_complete": False,
        "untrusted": True,
    }
    selection = _selection(job.goal)
    intent = json.loads(job.bindings).get("intent") or {}
    content_accounts = {
        item["integration_id"] for item in intent.get("requirements", [])
        if item.get("kind") == "document_content"
    }
    single_source = (selection is None and intent.get("mode") == "observe"
                     and intent.get("confidence") == "certain"
                     and bound_content_reference(job.goal,
                                                 semantic_followup=intent.get("followup") is True)
                     and bool(content_accounts))
    if selection is None and not single_source:
        return result
    searches: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for receipt in receipts:
        if receipt["tool"] != "paperless.read":
            continue
        normalized = _paperless(receipt["document"], receipt["result"])
        if single_source and receipt["reference"]["integration_id"] not in content_accounts:
            continue
        message = db.get(Message, receipt["reference"]["message_id"])
        if message is not None:
            data = normalized["data"] if normalized["operation"] == "search" else {
                "results": [normalized["data"]], "has_next": False, "document_receipt": True,
            }
            searches.append((message.created, receipt, data))
    if not searches:
        return result
    if single_source:
        latest = max(item[0] for item in searches)
        searches = [item for item in searches if item[0] == latest]
        identities = {(receipt["reference"]["integration_id"], row["id"])
                      for _, receipt, data in searches for row in data["results"]}
        if len(identities) != 1:
            return result  # No guessing a document/account from a multi-document cohort.
        _, identifier = identities.pop()
        selection = ("id", identifier)
    assert selection is not None
    if selection[0] == "id":
        matches = [
            (created, receipt, data, index, row)
            for created, receipt, data in searches
            for index, row in enumerate(data["results"])
            if row["id"] == selection[1]
        ]
        if not matches or len({m[1]["reference"]["integration_id"] for m in matches}) != 1:
            return result
        # Duplicate observations of the same account/ID use the latest receipt.
        _, receipt, data, index, row = max(
            matches, key=lambda item: (item[0], item[1]["reference"]["sequence"])
        )
    else:
        latest = max(item[0] for item in searches)
        searches = [item for item in searches if item[0] == latest]
        # An ordinal across accounts has no observed common ordering.
        if len({item[1]["reference"]["integration_id"] for item in searches}) != 1:
            return result
        _, receipt, data = max(searches, key=lambda item: item[1]["reference"]["sequence"])
        if not 1 <= selection[1] <= len(data["results"]):
            return result
        index, row = selection[1] - 1, data["results"][selection[1] - 1]
    ref = receipt["reference"]
    rows = data["results"]
    account = ref["integration_id"]
    profile, rules, _ = profiles[account]
    if profile.kind != "paperless" or not rules.enabled:
        return result
    try:
        args, effect = validate_tool(
            "paperless",
            rules,
            "paperless.read",
            {
                "operation": "document",
                "document_id": row["id"],
            },
        )
    except (ValueError, PermissionError):
        return result
    if effect or _attempted(job, profiles, history, account, row["id"]):
        return result
    result["source_receipts"] = [
        {
            "source_id": f"agent-read:{ref['source_job_id']}:{ref['sequence']}",
            "integration_id": account,
            "result_sha256": ref["result_sha256"],
            "document_sha256": ref["document_sha256"],
            "returned_count": len(rows),
            "more_pages": data["has_next"],
        }
    ]
    result["source_rows"] = len(rows)
    result["source_rows_omitted"] = len(rows) - 1
    result["decisions"] = [
        {
            "kind": "tool",
            "integration_id": account,
            "tool": "paperless.read",
            "arguments": args,
            "message": "Dokument anhand des gespeicherten Belegs lesen",
        }
    ]
    if data.get("document_receipt"):
        pointer = "/body" if receipt["document"]["tool"] == "http" else "/data"
    else:
        prefix = "/body/results/" if receipt["document"]["tool"] == "http" else "/data/results/"
        pointer = prefix + str(index)
    result["decision_sources"] = [{"source_index": 0, "pointer": pointer}]
    if len(encode(result).encode()) > max_bytes:
        raise ValueError("Archive source identity exceeds ready evidence budget")
    return result
