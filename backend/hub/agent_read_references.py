"""Revocable references to same-conversation private read receipts.

A reference supplies evidence only. It cannot select a new account, grant a tool,
replay a read, or turn an assistant's prose into an integration observation.
"""

import json
import re
import time
from typing import Any

from sqlalchemy import select

from hub.action_api import digest, encode
from hub.agent_failures import read_result_failure
from hub.agent_models import AgentJob, AgentPolicy, AgentStep
from hub.agent_tools import Rules, ha_metadata_read, validate_tool
from hub.db import Conversation, Message
from hub.integrations import Integration
from hub.policy import ContextPart

_PREFIX = "agent-read:"
_FIELDS = {
    "version", "message_id", "message_revision", "source_job_id", "sequence",
    "document_sha256", "result_sha256", "integration_id", "profile_revision",
    "config_sha256", "policy_revision",
}
_COMPLETED = {"observed", "succeeded"}
_MAIL_TOOLS = {"search_emails", "list_emails", "read_email", "get_thread", "daily_digest"}


def _binding(job: AgentJob, identifier: str) -> dict[str, Any] | None:
    return next(
        (b for b in json.loads(job.bindings)["profiles"] if b["id"] == identifier), None
    )


def _paperless(
    document: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Validate typed receipts or conservatively normalize legacy HTTP 200 reads."""
    from hub.paperless_client import metadata

    args = document["arguments"]
    legacy = document["tool"] == "http"
    if legacy:
        if read_result_failure("http", result) is not None:
            raise ValueError("Not a valid successful archive read")
        path = args["path"]
        if args["method"] != "GET" or result.get("http_status") != 200:
            raise ValueError("Not a successful archive read")
        if path == "/api/documents/":
            operation, data = "search", result["body"]
        elif re.fullmatch(r"/api/documents/[1-9][0-9]*/", path):
            operation, data = "document", result["body"]
        else:
            raise ValueError("Not an archive document receipt")
    else:
        operation, data = result["operation"], result["data"]
        if result.get("label") != "LOCAL_ONLY" or operation != args["operation"]:
            raise ValueError("Archive receipt does not match request")
    if operation == "document":
        row = metadata(data, include_content=True)
        if type(data.get("content_truncated", False)) is not bool:
            raise ValueError("Invalid archive truncation evidence")
        row["content_truncated"] |= data.get("content_truncated", False)
        expected = int(args["path"].split("/")[-2]) if legacy else args["document_id"]
        if row["id"] != expected:
            raise ValueError("Archive document mismatch")
        normalized = row
    elif operation == "search":
        if (
            not isinstance(data, dict)
            or type(data.get("count")) is not int
            or not isinstance(data.get("results"), list)
            or data["count"] < len(data["results"])
        ):
            raise ValueError("Invalid archive search receipt")
        rows = [metadata(row) for row in data["results"]]
        if legacy:
            # Legacy pagination is not inferred from URLs, query text or row count.
            page, size, more = 1, max(1, len(rows)), bool(data.get("next"))
        else:
            page, size, more = data["page"], data["page_size"], data["has_next"]
            if (
                type(page) is not int or page != args["page"]
                or type(size) is not int or size != args["limit"]
                or type(more) is not bool or len(rows) > size
            ):
                raise ValueError("Archive pagination mismatch")
        normalized = {
            "results": rows, "count": data["count"], "page": page,
            "page_size": size, "has_next": more,
        }
    else:
        raise ValueError("Unknown archive receipt")
    return {"label": "LOCAL_ONLY", "operation": operation, "data": normalized}



def _native_read(
    kind: str, tool: str, args: dict[str, Any], result: dict[str, Any], rules: Rules
) -> None:
    """Accept only concrete existing native read contracts, never arbitrary tools."""
    if read_result_failure(tool, result) is not None:
        raise ValueError("Native read result failed its shared completion contract")
    if tool == "http" and kind in {"home_assistant", "unifi", "paperless"}:
        status = result.get("http_status")
        if (
            args["method"] == "GET" and type(status) is int and 200 <= status < 300
            and "body" in result
        ):
            return
    elif tool == "ha.websocket" and kind == "home_assistant":
        if ha_metadata_read(args) and "response" in result and result.get("success") is not False:
            return
    elif tool == "ssh.inspect" and kind == "ssh":
        if (
            type(result.get("exit_code")) is int and result["exit_code"] == 0
            and isinstance(result.get("stdout"), str) and result["stdout"].strip()
            and isinstance(result.get("stderr"), str)
        ):
            return
    elif tool == "file.read" and kind == "ssh":
        path = result.get("path")
        if isinstance(path, str) and type(result.get("exists")) is bool:
            validate_tool(kind, rules, tool, {"path": path})
            if not result["exists"]:
                return
            text, sha = result.get("text"), result.get("sha256")
            if (
                isinstance(text, str) and isinstance(sha, str)
                and re.fullmatch(r"[a-f0-9]{64}", sha) and digest(text) == sha
            ):
                return
    elif tool == "gmail.read" and kind == "gmail":
        _gmail_read(args, result)
        return
    raise ValueError("Not a supported successful native read receipt")


def _gmail_read(args: dict[str, Any], result: dict[str, Any]) -> None:
    """Recheck native account-bound identities without interpreting mail as policy."""
    operation, data = result.get("operation"), result.get("data")
    if result.get("label") != "LOCAL_ONLY" or operation != args["operation"] or not isinstance(
        data, dict
    ):
        raise ValueError("Invalid native Gmail receipt")

    def identity(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9]{1,64}", value) is not None

    if operation == "search":
        rows = data.get("messages")
        valid = (
            isinstance(rows, list) and len(rows) <= args["limit"]
            and all(isinstance(row, dict) and identity(row.get("id"))
                    and identity(row.get("threadId")) for row in rows)
        )
    elif operation == "message":
        valid = (
            data.get("id") == args["message_id"] and identity(data.get("threadId"))
            and isinstance(data.get("headers"), dict) and isinstance(data.get("text"), str)
        )
    elif operation == "thread":
        rows = data.get("messages")
        valid = (
            data.get("id") == args["message_id"] and isinstance(rows, list) and len(rows) <= 20
            and all(isinstance(row, dict) and identity(row.get("id"))
                    and row.get("threadId") == data["id"] for row in rows)
        )
    elif operation == "labels":
        rows = data.get("labels")
        valid = (
            isinstance(rows, list) and len(rows) <= 1000
            and all(isinstance(row, dict) and isinstance(row.get("id"), str)
                    and isinstance(row.get("name"), str) for row in rows)
        )
    elif operation == "profile":
        valid = (
            isinstance(data.get("emailAddress"), str)
            and re.fullmatch(r"[^\s@]+@[^\s@]+", data["emailAddress"]) is not None
            and all(type(data.get(field)) is int and data[field] >= 0
                    for field in ("messagesTotal", "threadsTotal"))
        )
    else:
        valid = False
    if not valid:
        raise ValueError("Native Gmail read identity does not match its request")


def _receipt(
    db: Any, job: AgentJob, message: Message, step: AgentStep, profiles: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Recompute current identity, authority and receipt shape; never call a tool."""
    source = db.get(AgentJob, message.agent_job_id)
    if (
        job.scope != "conversation" or job.owner_id != job.conversation_id
        or not message.active or message.role != "assistant"
        or message.conversation_id != job.conversation_id
        or not source or source.id == job.id or source.scope != "conversation"
        or source.owner_id != job.owner_id or source.conversation_id != job.conversation_id
        or source.status not in _COMPLETED or step.job_id != source.id
        or message.created > job.created or source.created > job.created
        or step.created > job.created
        or step.kind != "read" or step.status != "succeeded"
        or digest(step.document) != step.sha256
    ):
        raise PermissionError("Private read source is no longer valid")
    document, result = json.loads(step.document), json.loads(step.result)
    if not isinstance(document, dict) or not isinstance(result, dict):
        raise ValueError("Invalid private read receipt")
    identifier = document["integration_id"]
    profile, rules, config = profiles[identifier]
    current = db.get(Integration, identifier)
    policy = db.get(AgentPolicy, identifier)
    target = document["target"]
    if not isinstance(target, dict):
        raise ValueError("Invalid private read target")
    url_matches = target.get("url") == config.get("url")
    if not url_matches and document.get("capability_inspection") is True and "url" not in target:
        from hub.agent_capabilities import bootstrap

        inspection = bootstrap(current, rules) if current else None
        url_matches = inspection is not None and all(
            document.get(key) == inspection[key] for key in ("tool", "arguments")
        )
    bound, prior = _binding(job, identifier), _binding(source, identifier)
    if (
        not current or not current.enabled or not policy or not rules.enabled
        or profile.id != identifier or profile.revision != current.revision
        or profile.config != current.config or config.get("kind") != current.kind
        or config.get("url") != json.loads(current.config).get("url")
        or policy.profile_revision != current.revision
        or Rules.model_validate_json(policy.rules).model_dump() != rules.model_dump()
        or not bound or not prior
        or any(b["profile_revision"] != current.revision for b in (bound, prior))
        or any(b["policy_revision"] != policy.revision for b in (bound, prior))
        or target.get("kind") != current.kind
        or not url_matches
        or target.get("profile_revision") != current.revision
        or target.get("config_sha256") != digest(current.config)
        or target.get("policy_revision", policy.revision) != policy.revision
    ):
        raise PermissionError("Private read target or permission changed")
    args, effect = validate_tool(current.kind, rules, document["tool"], document["arguments"])
    if effect:
        raise PermissionError("Effects cannot become private read references")
    if document["tool"] == "mcp.call" and args["name"] in _MAIL_TOOLS:
        from hub.agent_mail_read import model_result

        if model_result(args["name"], result, account_id=identifier, max_bytes=512) is None:
            raise ValueError("Invalid mailbox receipt")
        tool = args["name"]
    elif current.kind == "paperless" and (
        document["tool"] == "paperless.read"
        or document["tool"] == "http" and args["path"].startswith("/api/documents")
    ):
        _paperless({**document, "arguments": args}, result)
        tool = "paperless.read"
    else:
        _native_read(current.kind, document["tool"], args, result, rules)
        tool = document["tool"]
    reference = {
        "version": 1, "message_id": message.id, "message_revision": message.revision,
        "source_job_id": source.id, "sequence": step.sequence,
        "document_sha256": step.sha256, "result_sha256": digest(step.result),
        "integration_id": identifier, "profile_revision": current.revision,
        "config_sha256": digest(current.config), "policy_revision": policy.revision,
    }
    return reference, result, tool


def bind(
    db: Any, job: AgentJob, messages: list[Message], profiles: dict[str, Any]
) -> list[dict[str, Any]]:
    """Freeze up to two latest valid receipts; ignore ineligible earlier messages."""
    if job.scope != "conversation":
        return []
    refs: dict[tuple[str, int], dict[str, Any]] = {}
    for message in sorted(messages[-12:], key=lambda m: m.created, reverse=True):
        if not message.agent_job_id:
            continue
        receipts = db.scalars(
            select(AgentStep).where(AgentStep.job_id == message.agent_job_id)
            .order_by(AgentStep.sequence.desc())
        )
        for step in receipts:
            try:
                reference, _, _ = _receipt(db, job, message, step, profiles)
            except (KeyError, TypeError, ValueError, PermissionError):
                continue
            key = (step.job_id, step.sequence)
            if key in refs:
                continue
            refs[key] = ContextPart(
                source_id=f"{_PREFIX}{step.job_id}:{step.sequence}", revision=1,
                content=encode(reference),
            ).model_dump(mode="json")
            if len(refs) == 2:
                return list(refs.values())
    return list(refs.values())


def _validated(
    db: Any, job: AgentJob, profiles: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    valid: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    seen = set()
    for part in json.loads(job.context):
        if not str(part.get("source_id", "")).startswith(_PREFIX):
            continue
        try:
            if (
                len(valid) >= 2 or part.get("label") != "LOCAL_ONLY"
                or type(part["revision"]) is not int or part["revision"] != 1
            ):
                raise ValueError("Invalid private read context")
            ref = json.loads(part["content"])
            if (
                not isinstance(ref, dict) or set(ref) != _FIELDS
                or ref.get("version") != 1
                or any(type(ref[k]) is not int or ref[k] < 1 for k in (
                    "version", "message_revision", "sequence", "profile_revision",
                    "policy_revision",
                ))
                or any(not isinstance(ref[k], str) or not ref[k] for k in (
                    "message_id", "source_job_id", "integration_id",
                ))
                or any(not isinstance(ref[k], str)
                       or not re.fullmatch(r"[a-f0-9]{64}", ref[k]) for k in (
                           "document_sha256", "result_sha256", "config_sha256",
                       ))
            ):
                raise ValueError("Invalid private read reference")
            message = db.get(Message, ref["message_id"])
            step = db.get(AgentStep, (ref["source_job_id"], ref["sequence"]))
            if not message or not step:
                raise ValueError("Private read source removed")
            actual, result, tool = _receipt(db, job, message, step, profiles)
            if (
                ref != actual
                or part["source_id"] != f"{_PREFIX}{step.job_id}:{step.sequence}"
                or part["source_id"] in seen
            ):
                raise ValueError("Private read provenance changed")
            seen.add(part["source_id"])
            valid.append((actual, result, tool))
        except (KeyError, TypeError, ValueError, PermissionError):
            raise PermissionError("Bound private read evidence changed or was revoked") from None
    return valid


def validate(db: Any, job: AgentJob, profiles: dict[str, Any]) -> None:
    """Recheck every bound receipt at the ordinary final permission boundary."""
    _validated(db, job, profiles)


def model_context(
    db: Any, job: AgentJob, profiles: dict[str, Any], *, max_bytes: int = 1800
) -> list[dict[str, Any]]:
    """Typed bounded observations; identifiers and provenance are never clipped."""
    if max_bytes < 512:
        raise ValueError("Private read evidence budget must be at least 512 bytes")
    observations: list[dict[str, Any]] = []
    validated = _validated(db, job, profiles)
    for index, (ref, result, tool) in enumerate(validated):
        item = {
            "source_id": f"{_PREFIX}{ref['source_job_id']}:{ref['sequence']}",
            "integration_id": ref["integration_id"], "tool": tool,
            "result_sha256": ref["result_sha256"], "label": "LOCAL_ONLY",
            "untrusted": True, "projection_omitted": True,
        }
        # Reserve the full wrapper and explicit omission record before projecting.
        remaining = (
            max_bytes - len(encode([*observations, item]).encode()) - 24
            - sum(320 + len(later[0]["integration_id"])
                  for later in validated[index + 1:])
        )
        if remaining >= 512:
            if tool in _MAIL_TOOLS:
                from hub.agent_mail_read import model_result

                projection = model_result(
                    tool, result, account_id=ref["integration_id"], max_bytes=remaining
                )
            elif tool == "paperless.read":
                from hub.agent_paperless import model_result as paperless_model_result

                source_step = db.get(AgentStep, (ref["source_job_id"], ref["sequence"]))
                projection = paperless_model_result(
                    _paperless(json.loads(source_step.document), result), max_bytes=remaining
                )
            else:
                from hub.agent_context import view

                projection = view(result, remaining)
            item.update(result=projection, projection_omitted=False)
        if len(encode([*observations, item]).encode()) > max_bytes:
            raise ValueError("Private read provenance exceeds the evidence budget")
        observations.append(item)
    return observations


def previous_profile_ids(
    db: Any, conversation_id: str, profiles: dict[str, Any]
) -> set[str]:
    """Resolve anaphora to already approved targets, without creating any job."""
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.archived or conversation.purpose != "chat":
        return set()
    bindings = []
    for identifier in profiles:
        policy = db.get(AgentPolicy, identifier)
        profile = db.get(Integration, identifier)
        if policy and profile:
            bindings.append({
                "id": identifier, "profile_revision": profile.revision,
                "policy_revision": policy.revision,
            })
    # This transient object is never added, flushed, enqueued or dispatched.
    candidate = AgentJob(
        id="unpersisted-read-reference", scope="conversation", owner_id=conversation_id,
        conversation_id=conversation_id, bindings=encode({"profiles": bindings}),
        created=time.time(),
    )
    messages = list(db.scalars(
        select(Message).where(
            Message.conversation_id == conversation_id, Message.active.is_(True),
            Message.role == "assistant",
        ).order_by(Message.created.desc()).limit(12)
    ))
    return {json.loads(part["content"])["integration_id"]
            for part in bind(db, candidate, messages, profiles)}


def validated_receipts(
    db: Any, job: AgentJob, profiles: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return full, currently authorized evidence for local application planning.

    These copied source documents and results confer no execution authority. Every
    subsequent read still needs its current observed schema and final dispatch gate.
    Never obtain identities from a shortened model view or assistant prose.
    """
    receipts = []
    for reference, result, tool in _validated(db, job, profiles):
        step = db.get(AgentStep, (reference["source_job_id"], reference["sequence"]))
        if (
            not step
            or digest(step.document) != reference["document_sha256"]
            or digest(step.result) != reference["result_sha256"]
        ):
            raise PermissionError("Private read provenance changed")
        receipts.append({
            "reference": reference,
            "document": json.loads(step.document),
            "result": result,
            "tool": tool,
        })
    return receipts
