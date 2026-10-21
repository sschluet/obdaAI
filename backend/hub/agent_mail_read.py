"""Bounded, inert mailbox receipts and conservative reply relationships.

These helpers derive evidence, never permissions. Callers must retain the original
receipt and perform the ordinary current-account and tool permission checks.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

TOOLS = {"list_emails", "search_emails", "daily_digest", "read_email", "get_thread"}
_ID = re.compile(r"<[^<>\s]+>")


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _identifier(value: Any) -> str | None:
    if (
        isinstance(value, str)
        and value
        and len(value.encode()) <= 512
        and not any(c in value for c in "\r\n")
    ):
        return value
    return None


def _text(value: Any, limit: int) -> tuple[str, bool]:
    if not isinstance(value, str):
        return "", False
    raw = value.encode()
    return raw[:limit].decode("utf-8", errors="ignore"), len(raw) > limit


def _row(message: Mapping[str, Any], *, body: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {"untrusted": True}
    omitted = []
    for key in ("message_id", "in_reply_to", "folder"):
        value = _identifier(message.get(key))
        if value is not None:
            row[key] = value
        elif message.get(key):
            omitted.append(key)
    if type(message.get("uid")) is int and message["uid"] > 0:
        row["uid"] = message["uid"]
    for key, limit in (
        ("subject", 160),
        ("sender", 160),
        ("recipients", 160),
        ("date", 96),
        ("received", 96),
    ):
        row[key], clipped = _text(message.get(key), limit)
        if clipped:
            omitted.append(key)
    row["in_reply_to_observed"] = isinstance(message.get("in_reply_to"), str)
    row["references_observed"] = isinstance(message.get("references"), str)
    references = message.get("references")
    if isinstance(references, str):
        ids = list(dict.fromkeys(_ID.findall(references)))
        row["references"] = [mid for mid in ids[:12] if _identifier(mid)]
        if len(ids) > 12 or len(row["references"]) != len(ids):
            omitted.append("references")
    row["marked_answered"] = (
        message.get("answered") if type(message.get("answered")) is bool else None
    )
    row["answer_status_basis"] = (
        "reported_imap_answered_flag" if row["marked_answered"] is not None else "not_exposed"
    )
    if body:
        row["body_text"], clipped = _text(message.get("body_text"), 800)
        source_body = message.get("body_text")
        row["body_bytes_omitted"] = (
            max(0, len(source_body.encode()) - len(row["body_text"].encode()))
            if isinstance(source_body, str)
            else 0
        )
        row["body_source_truncated"] = message.get("truncated") is True
        if clipped or row["body_source_truncated"]:
            omitted.append("body_text")
    row["omitted_or_clipped_fields"] = omitted
    return row


def model_result(
    tool_name: str,
    result: dict[str, Any],
    *,
    max_bytes: int = 3000,
    account_id: str | None = None,
) -> dict[str, Any] | None:
    """Project known actual MCP receipts; never derive evidence from tool schemas."""
    if tool_name not in TOOLS:
        return None
    response = result.get("response")
    if (
        not isinstance(response, dict)
        or response.get("is_error") is True
        or response.get("isError") is True
    ):
        return None
    content = response.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], str):
        return None
    try:
        payload = json.loads(content[0])
    except (ValueError, TypeError):
        return None
    if tool_name == "read_email":
        messages = [payload] if isinstance(payload, dict) else None
    elif tool_name == "get_thread":
        messages = (
            payload
            if isinstance(payload, list)
            else payload.get("messages")
            if isinstance(payload, dict)
            else None
        )
    else:
        messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
        return None
    if max_bytes < 512:
        raise ValueError("Mailbox evidence budget must be at least 512 bytes")
    projected: dict[str, Any] = {
        "model_projection": "mail_read_metadata",
        "tool": tool_name,
        "full_sha256": hashlib.sha256(_encode(result).encode()).hexdigest(),
        "untrusted": True,
        "returned_count": len(messages),
        "messages": [],
        "messages_omitted": len(messages),
        "completeness_verified": False,
        "coverage": "thread_members_only"
        if tool_name == "get_thread"
        else "single_message"
        if tool_name == "read_email"
        else "bounded_query",
        "upstream_truncated": payload.get("truncated") is True
        if isinstance(payload, dict)
        else None,
        "upstream_more_pages": bool(payload.get("next_cursor"))
        if isinstance(payload, dict)
        else None,
    }
    for message in messages:
        row = _row(message, body=tool_name == "read_email")
        # Account identity is application-bound, never accepted from remote JSON.
        if account_id is not None:
            row["account_id"] = account_id
        projected["messages"].append(row)
        projected["messages_omitted"] -= 1
        if len(_encode(projected).encode()) > max_bytes and "body_text" in row:
            row["body_bytes_omitted"] += len(row.pop("body_text").encode())
            if "body_text" not in row["omitted_or_clipped_fields"]:
                row["omitted_or_clipped_fields"].append("body_text")
        # Stable references and flags precede presentation text in the budget.
        for key in ("recipients", "date", "received", "subject", "sender"):
            if len(_encode(projected).encode()) <= max_bytes:
                break
            if row.get(key):
                row.pop(key)
                if key not in row["omitted_or_clipped_fields"]:
                    row["omitted_or_clipped_fields"].append(key)
            else:
                row.pop(key, None)
        if len(_encode(projected).encode()) > max_bytes:
            projected["messages"].pop()
            projected["messages_omitted"] += 1
            projected["first_omitted_message_pointer"] = (
                "/" + str(len(projected["messages"]))
                if tool_name == "get_thread" and isinstance(payload, list)
                else ""
                if tool_name == "read_email"
                else "/messages/" + str(len(projected["messages"]))
            )
            break
    return projected


def reply_evidence(
    messages: Sequence[Mapping[str, Any]],
    sent_messages: Sequence[Mapping[str, Any]],
    *,
    sent_folders: Sequence[Mapping[str, Any]],
    account_id: str,
) -> list[dict[str, Any]]:
    """Prove positive links only from same-account messages in observed Sent folders.

    A missing link is unknown, including when the Answered flag is false. Sent
    membership documents the stored relationship, never SMTP delivery or authorship.
    No subject, display name, text similarity or foreign thread member is evidence.
    """
    folders = {
        f["name"]
        for f in sent_folders
        if f.get("account_id") == account_id
        and isinstance(f.get("name"), str)
        and f.get("selectable") is True
        and isinstance(f.get("flags"), list)
        and "\\Sent" in f["flags"]
    }
    sent = [
        m for m in sent_messages if m.get("account_id") == account_id and m.get("folder") in folders
    ]
    output = []
    for message in messages:
        if message.get("account_id") != account_id:
            continue
        mid = _identifier(message.get("message_id"))
        links = []
        if mid:
            for candidate in sent:
                candidate_id = _identifier(candidate.get("message_id"))
                if not candidate_id or candidate_id == mid:
                    continue
                direct = candidate.get("in_reply_to") == mid
                references = candidate.get("references")
                chain = isinstance(references, str) and mid in _ID.findall(references)
                if direct or chain:
                    links.append(
                        {
                            "message_id": candidate_id,
                            "folder": candidate["folder"],
                            "basis": "in_reply_to" if direct else "references",
                        }
                    )
        output.append(
            {
                "account_id": account_id,
                "message_id": mid,
                "marked_answered": message.get("answered")
                if type(message.get("answered")) is bool
                else None,
                "sent_reply_status": "verified_sent_folder_relationship" if links else "unknown",
                "sent_reply_evidence": links,
                "delivery_verified": False,
                "completeness_verified": False,
            }
        )
    return output
