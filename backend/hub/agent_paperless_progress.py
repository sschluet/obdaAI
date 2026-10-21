"""Inert document choices from full, currently authorized archive receipts.

No model prose, remote requests, new grants or automatic retries. The shared agent
still owns its fresh gate, native grammar, durable intent and final dispatch.
"""

import json
import re
from typing import Any

from hub.action_api import digest, encode
from hub.agent_models import AgentJob, AgentStep
from hub.agent_read_references import _paperless, validated_receipts
from hub.agent_tools import validate_tool
from hub.db import Message

_CONTENT = re.compile(
    r"zusammenfass|\bfasse\b|\binhalt\b|\bocr\b|\blesen\b|\blies\b|"
    r"\bzeige\b|\benthält\b|\bsteht\b|summari|\bread\b|\bcontent\b",
    re.I,
)
_OTHER = re.compile(
    r"\b(?:suche|such|finde|filtere|durchsuche|search|find|filter|"
    r"lösche|lösch|entferne|ändere|änder|benenne|umbenennen|speichere|"
    r"sende|verschicke|exportiere|download|herunterladen|hochladen|"
    r"delete|remove|rename|update|write|send|export|upload)\b",
    re.I,
)
_ORDINALS = {
    "erst": 1,
    "zweit": 2,
    "dritt": 3,
    "viert": 4,
    "fünft": 5,
    "sechst": 6,
    "siebt": 7,
    "acht": 8,
    "neunt": 9,
    "zehnt": 10,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
}


def _selection(goal: str) -> tuple[str, int] | None:
    """Interpret resource references only; never decide that the goal is complete."""
    # A bound prior-search noun phrase is a reference, not a request to search again.
    action_goal = re.sub(
        r"\b(?:aus|von|in)\s+(?:der|deiner|unserer|meiner|dieser)\s+"
        r"(?:letzten|vorherigen|bisherigen)\s+(?:suche|abfrage)\b|"
        r"\bfrom\s+(?:the|your|our|my)\s+(?:last|previous)\s+search\b",
        "",
        goal,
        flags=re.I,
    )
    if not _CONTENT.search(goal) or _OTHER.search(action_goal):
        return None
    if re.search(
        r"\b(?:nur|mindestens|höchstens|where|filtered)\b|"
        r"\b(?:von|seit|vor|nach|mit|ohne)\s+\d",
        goal,
        re.I,
    ):
        return None
    ids = re.findall(
        r"\b(?:dokument|document)(?:[-\s]*(?:id|nr\.?|nummer|number))?"
        r"\s*[:#]?\s*([1-9][0-9]*)\b",
        goal,
        re.I,
    )
    # Asking to *name* an ID is not an explicit ID selection.
    if ids:
        return ("id", int(ids[0])) if len(set(ids)) == 1 else None
    if re.search(r"\bdokument[-\s]*(?:id|nummer)\s*[:#]?\s*0\b", goal, re.I):
        return None
    if re.search(
        r"\bdie\s+(?:ersten|zweiten|dritten|vierten|fünften|sechsten|siebten|achten|neunten|zehnten)"
        r"\s+(?:(?:gefunden|angezeigt)(?:en)?\s+)?treffer\b",
        goal,
        re.I,
    ):
        return None
    ordinals = []
    for stem, number in _ORDINALS.items():
        pattern = (
            rf"\b{stem}(?:e|en|er|es|em)?\s+"
            r"(?:(?:gefunden|angezeigt|beobachtet|found|listed)(?:e|en|er|es|em)?\s+)?"
            r"(?:dokument(?:s)?|document|treffer(?:s)?|result|hit)\b"
        )
        if re.search(pattern, goal, re.I):
            ordinals.append(number)
    ordinals.extend(
        int(n)
        for n in re.findall(
            r"\b([1-9][0-9]*)\.\s+(?:(?:gefunden|angezeigt|beobachtet)(?:e|en|er|es|em)?\s+)?"
            r"(?:dokument(?:s)?|treffer(?:s)?)\b",
            goal,
            re.I,
        )
    )
    return ("ordinal", ordinals[0]) if len(set(ordinals)) == 1 else None


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
    if selection is None:
        return result
    searches = []
    for receipt in receipts:
        if receipt["tool"] != "paperless.read":
            continue
        normalized = _paperless(receipt["document"], receipt["result"])
        if normalized["operation"] != "search":
            continue
        message = db.get(Message, receipt["reference"]["message_id"])
        if message is not None:
            searches.append((message.created, receipt, normalized["data"]))
    if not searches:
        return result
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
    prefix = "/body/results/" if receipt["document"]["tool"] == "http" else "/data/results/"
    result["decision_sources"] = [{"source_index": 0, "pointer": prefix + str(index)}]
    if len(encode(result).encode()) > max_bytes:
        raise ValueError("Archive source identity exceeds ready evidence budget")
    return result
