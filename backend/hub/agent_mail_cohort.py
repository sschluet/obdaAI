"""Read-only evidence for the exact, revocable previously displayed mail cohort."""

import json
from typing import Any

from hub.action_api import digest, encode
from hub.agent_mail_read import reply_evidence
from hub.agent_models import AgentJob, AgentStep
from hub.agent_read_references import validated_receipts
from hub.agent_tools import validate_tool
from hub.db import Message


def _payload(result: dict[str, Any]) -> Any:
    response = result["response"]
    content = response["content"]
    if response.get("is_error") or response.get("isError") or len(content) != 1:
        raise ValueError("Not a successful single mailbox receipt")
    return json.loads(content[0])


def selected_receipt_rows(
    db: Any, job: AgentJob, profiles: dict[str, Any], receipts: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Recover displayed rows only if bound receipts reproduce the displayed answer.

    ``receipts`` is an optimization for callers holding fresh validated_receipts,
    never a substitute for their current revocation check. No unbound source reads
    are loaded, even when the two-reference cap omitted an earlier query.
    """
    from hub.agent_runtime import (
        displayed_mail_records,
        mail_header_identity,
        mail_overview_records,
        mail_overview_summary,
        mail_query_payload,
    )

    actual = validated_receipts(db, job, profiles)
    if receipts is not None and receipts != actual:
        raise PermissionError("Private read receipts changed")
    unknown = {"cohort_known": False, "rows": [], "reason": "display_scope_not_reconstructable"}
    if not actual:
        return unknown
    messages = [db.get(Message, r["reference"]["message_id"]) for r in actual]
    latest = max((m for m in messages if m is not None), key=lambda m: m.created)
    selected = [r for r in actual if r["reference"]["message_id"] == latest.id]
    source = db.get(AgentJob, latest.agent_job_id)
    if source is None or latest.content != source.summary:
        return unknown
    steps = []
    raw: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        clock = json.loads(source.bindings)["clock"]
        for receipt in sorted(selected, key=lambda r: r["reference"]["sequence"]):
            ref = receipt["reference"]
            step = db.get(AgentStep, (ref["source_job_id"], ref["sequence"]))
            parsed = mail_query_payload(step)
            if parsed is None:
                continue
            steps.append(step)
            for row in parsed[1]["messages"]:
                key = (ref["integration_id"], mail_header_identity(row))
                raw.setdefault(key, {"integration_id": key[0], "row": row, "reference": ref})
        summary = mail_overview_summary(steps, clock, source.goal, profiles)
        if summary is None or summary != source.summary:
            return unknown
        records, scopes, _ = mail_overview_records(steps, clock, source.goal)
        shown = displayed_mail_records(records)
        rows = [
            raw[(account, view["identity_sha256"])]
            for account in scopes
            for known in (True, None)
            for selected_account, view in shown
            if selected_account == account and view["in_requested_window"] is known
        ]
    except (KeyError, TypeError, ValueError):
        return unknown
    identities = [(r["integration_id"], mail_header_identity(r["row"])) for r in rows]
    refs = [
        r["reference"]
        for r in selected
        if r["tool"] in {"list_emails", "search_emails", "daily_digest"}
    ]
    return {
        "cohort_known": True,
        "rows": rows,
        "cohort_sha256": digest(encode(identities)),
        "source_receipts": [
            {
                "source_id": f"agent-read:{r['source_job_id']}:{r['sequence']}",
                "result_sha256": r["result_sha256"],
            }
            for r in refs
        ],
    }


def current_mail_observations(
    job: AgentJob, profiles: dict[str, Any], history: list[AgentStep]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    folders: list[dict[str, Any]] = []
    hashes: list[str] = []
    discovered: set[str] = set()
    discovery_sequences: dict[str, int] = {}
    queries: list[dict[str, Any]] = []
    for step in sorted(history, key=lambda s: s.sequence):
        if step.job_id != job.id or step.kind != "read" or step.status != "succeeded":
            continue
        try:
            if digest(step.document) != step.sha256:
                continue
            document = json.loads(step.document)
            account = document["integration_id"]
            profile, rules, config = profiles[account]
            target = document["target"]
            if (
                not profile.enabled
                or not rules.enabled
                or target.get("kind") != profile.kind
                or target.get("url") != config.get("url")
                or target.get("profile_revision") != profile.revision
                or target.get("config_sha256") != digest(profile.config)
            ):
                continue
            args, effect = validate_tool(
                profile.kind, rules, document["tool"], document["arguments"]
            )
            if effect or document["tool"] != "mcp.call":
                continue
            payload = _payload(json.loads(step.result))
            name = args["name"]
            if name == "list_folders" and isinstance(payload, list):
                if not all(
                    isinstance(f, dict)
                    and isinstance(f.get("name"), str)
                    and isinstance(f.get("flags"), list)
                    and type(f.get("selectable")) is bool
                    for f in payload
                ):
                    continue
                discovered.add(account)
                discovery_sequences[account] = step.sequence
                folders = [f for f in folders if f["account_id"] != account]
                folders.extend({**r, "account_id": account} for r in payload if isinstance(r, dict))
            elif name in {
                "read_email",
                "get_thread",
                "list_emails",
                "search_emails",
                "daily_digest",
            }:
                data = (
                    [payload]
                    if name == "read_email" and isinstance(payload, dict)
                    else payload
                    if isinstance(payload, list)
                    else payload.get("messages", [])
                    if isinstance(payload, dict)
                    else []
                )
                if not isinstance(data, list):
                    continue
                rows.extend({**r, "account_id": account} for r in data if isinstance(r, dict))
                requested = args["arguments"].get("folder")
                if (
                    name in {"list_emails", "search_emails"}
                    and isinstance(payload, dict)
                    and isinstance(payload.get("messages"), list)
                    and isinstance(requested, str)
                    and requested
                    and payload.get("folder", requested) == requested
                    and all(isinstance(r, dict) and r.get("folder") == requested for r in data)
                ):
                    queries.append(
                        {
                            "integration_id": account,
                            "folder": requested,
                            "sequence": step.sequence,
                            "result_sha256": digest(step.result),
                        }
                    )
            else:
                continue
            hashes.append(digest(step.result))
        except (KeyError, TypeError, ValueError, PermissionError):
            continue
    return {
        "rows": rows,
        "folders": folders,
        "hashes": hashes,
        "discovered_accounts": discovered,
        "discovery_sequences": discovery_sequences,
        "queries": queries,
    }


def cohort_evidence(
    db: Any,
    job: AgentJob,
    profiles: dict[str, Any],
    history: list[AgentStep],
    *,
    max_bytes: int = 1400,
) -> dict[str, Any]:
    """All displayed ordinals get flags or explicit unknowns; absence is never negative."""
    from hub.agent_runtime import mail_header_identity

    if max_bytes < 1024:
        raise ValueError("Cohort evidence requires at least 1024 bytes")
    selected = selected_receipt_rows(db, job, profiles)
    observations = current_mail_observations(job, profiles, history)
    current, folders, hashes = (observations[k] for k in ("rows", "folders", "hashes"))
    if not selected["cohort_known"]:
        fallback: dict[str, Any] = {
            "cohort_known": False,
            "reason": selected["reason"],
            "sent_coverage_complete": False,
            "proofs": [],
            "proofs_omitted": len(current),
            "current_receipts_sha256": digest(encode(hashes)),
        }
        for account in dict.fromkeys(row["account_id"] for row in current):
            proofs = reply_evidence(current, current, sent_folders=folders, account_id=account)
            for proof in proofs:
                proposed = {
                    **fallback,
                    "proofs": [*fallback["proofs"], proof],
                    "proofs_omitted": fallback["proofs_omitted"] - 1,
                }
                if len(encode(proposed).encode()) <= max_bytes:
                    fallback = proposed
        return fallback
    output, examples = [], []
    for ordinal, item in enumerate(selected["rows"], 1):
        account, original = item["integration_id"], item["row"]
        matches = [
            r
            for r in current
            if r["account_id"] == account
            and mail_header_identity(r) == mail_header_identity(original)
            and r.get("message_id") == original.get("message_id")
        ]
        fresh = next((r for r in reversed(matches) if type(r.get("answered")) is bool), None)
        observed = fresh if fresh is not None else original
        proof = reply_evidence(
            [{**observed, "account_id": account}], current, sent_folders=folders, account_id=account
        )[0]
        output.append(
            [
                ordinal,
                proof["marked_answered"],
                fresh is not None,
                True if proof["sent_reply_evidence"] else None,
            ]
        )
        subject = original.get("subject")
        if isinstance(subject, str) and subject:
            examples.append(
                {"entry": ordinal, "subject": subject.encode()[:72].decode(errors="ignore")}
            )
    accounts = {r["integration_id"] for r in selected["rows"]}
    sent = {
        (f["account_id"], f.get("name"))
        for f in folders
        if f.get("selectable") is True
        and isinstance(f.get("flags"), list)
        and "\\Sent" in f["flags"]
        and isinstance(f.get("name"), str)
    }
    attempted = {
        q["integration_id"]
        for q in observations["queries"]
        if (q["integration_id"], q["folder"]) in sent
        and q["sequence"]
        > observations["discovery_sequences"].get(q["integration_id"], q["sequence"])
    }
    result: dict[str, Any] = {
        "cohort_known": True,
        "sent_discovery_observed": bool(accounts)
        and accounts <= observations["discovered_accounts"],
        "sent_query_observed": bool(accounts) and accounts <= attempted,
        "cohort_sha256": selected["cohort_sha256"],
        "source_receipts": selected["source_receipts"],
        "displayed_count": len(output),
        "columns": ["entry", "marked_answered", "flag_refreshed", "sent_relationship"],
        "rows": output,
        "unknown_flag_count": sum(r[1] is None for r in output),
        "marked_answered_count": sum(r[1] is True for r in output),
        "current_flag_count": sum(r[2] for r in output),
        "current_receipts_sha256": digest(encode(hashes)),
        "false_flag_means_unanswered": False,
        "sent_coverage_complete": False,
        "flag_scope": "prior_snapshot_unless_refreshed",
        "examples": [],
        "examples_omitted": len(examples),
    }
    if len(encode(result).encode()) > max_bytes:
        return {
            "cohort_known": False,
            "reason": "evidence_budget",
            "cohort_sha256": selected["cohort_sha256"],
            "displayed_count": len(output),
            "sent_coverage_complete": False,
        }
    for example in examples:
        proposed = {
            **result,
            "examples": [*result["examples"], example],
            "examples_omitted": result["examples_omitted"] - 1,
        }
        if len(encode(proposed).encode()) <= max_bytes:
            result = proposed
    return result
