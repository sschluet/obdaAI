"""Bounded final-answer evidence from current typed archive reads, never model prose.

The caller must first run its fresh database permission/cancellation gate. This
pure formatter cannot grant authority, perform reads, or certify model conclusions.
"""

import json
import re
import string
import unicodedata
from typing import Any

from hub.action_api import digest
from hub.agent_models import AgentJob, AgentStep
from hub.agent_read_references import _paperless
from hub.agent_tools import validate_tool

_FOOTER = (
    "Die Angaben gelten jeweils für den genannten Abruf; Trefferzahlen verschiedener Suchen "
    "werden nicht addiert. Suchtreffer allein belegen keinen gelesenen Dokumentinhalt. "
    "Nicht abgerufene Seiten oder Dokumentinhalte sind dadurch nicht geprüft."
)


def _text(value: str, limit: int) -> str:
    clean = " ".join(
        "".join(" " if unicodedata.category(c).startswith("C") else c for c in value).split()
    )
    clipped = clean.encode()[:limit].decode("utf-8", errors="ignore")
    escaped = re.sub("([" + re.escape(string.punctuation) + "])", r"\\\1", clipped)
    return escaped + (" (gekürzt)" if clipped != clean else "")


def _binding(job: AgentJob, identifier: str) -> dict[str, Any]:
    bindings = json.loads(job.bindings)["profiles"]
    matches = [item for item in bindings if item["id"] == identifier]
    if len(matches) != 1:
        raise PermissionError("Archive profile is not uniquely bound")
    bound: dict[str, Any] = matches[0]
    if (
        type(bound.get("profile_revision")) is not int
        or type(bound.get("policy_revision")) is not int
    ):
        raise PermissionError("Archive revision binding is invalid")
    return bound


def _receipt(
    job: AgentJob, profiles: dict[str, Any], step: AgentStep, document: dict[str, Any]
) -> dict[str, Any]:
    identifier = document["integration_id"]
    profile, rules, config = profiles[identifier]
    bound = _binding(job, identifier)
    target = document["target"]
    saved_config = json.loads(profile.config)
    if (
        step.status != "succeeded"
        or digest(step.document) != step.sha256
        or profile.id != identifier
        or not profile.enabled
        or not rules.enabled
        or profile.kind != "paperless"
        or config.get("kind") != "paperless"
        or config.get("url") != saved_config.get("url")
        or any(config.get(key) != value for key, value in saved_config.items())
        or bound["profile_revision"] != profile.revision
        or target.get("kind") != "paperless"
        or target.get("url") != config.get("url")
        or type(target.get("profile_revision")) is not int
        or target.get("profile_revision") != profile.revision
        or target.get("config_sha256") != digest(profile.config)
        # Generic historical typed dispatch omits this field. The caller's fresh
        # DB gate supplies that check; an explicit differing revision is rejected.
        or ("policy_revision" in target and type(target["policy_revision"]) is not int)
        or target.get("policy_revision", bound["policy_revision"]) != bound["policy_revision"]
    ):
        raise PermissionError("Archive receipt is not current")
    args, effect = validate_tool(profile.kind, rules, "paperless.read", document["arguments"])
    if effect:
        raise PermissionError("Archive evidence must be read-only")
    raw = json.loads(step.result)
    normalized = _paperless({**document, "arguments": args}, raw)
    if normalized["operation"] == "search":
        data = normalized["data"]
        if data["has_next"] != (data["page"] * data["page_size"] < data["count"]):
            raise ValueError("Contradictory typed archive pagination")
    return {
        "source": profile.name,
        "sequence": step.sequence,
        "result_sha256": digest(step.result),
        "args": args,
        "result": normalized,
        "ocr_flag_observed": type(raw.get("data", {}).get("content_truncated")) is bool,
    }


def _block(receipt: dict[str, Any], *, titles: bool) -> str:
    result, args = receipt["result"], receipt["args"]
    data = result["data"]
    lines = [
        f"Quelle: {_text(receipt['source'], 96)} · Abrufschritt {receipt['sequence']}.",
    ]
    if result["operation"] == "search":
        query = _text(args["query"], 200) if args["query"] else "kein Suchfilter"
        lines.extend(
            [
                f"Suchfilter: {query}.",
                f"Seite {data['page']} · Seitengröße {data['page_size']} · "
                f"Gesamttreffer laut dieser Suchantwort: {data['count']} · "
                f"tatsächlich abgerufen: {len(data['results'])} · "
                f"weitere Seiten: {'ja' if data['has_next'] else 'nein'}.",
            ]
        )
        if data["results"]:
            rows = [
                f"ID {row['id']}" + (f" · {_text(row['title'], 64)}" if titles else "")
                for row in data["results"]
            ]
            lines.append("Treffer in tatsächlicher Abrufreihenfolge: " + "; ".join(rows) + ".")
            if not titles:
                lines.append("Titel ausgelassen (Ausgabegrenze); Dokument-IDs unverändert.")
        else:
            lines.append("Keine Treffer in dieser konkreten Suchantwort.")
    else:
        title = (
            f" · {_text(data['title'], 128)}" if titles else " · Titel ausgelassen (Ausgabegrenze)"
        )
        lines.append(f"Einzeldokument-Abruf: Dokument-ID {data['id']}{title}.")
        truncated = (
            ("ja" if data["content_truncated"] else "nein")
            if receipt["ocr_flag_observed"]
            else "im Abruf nicht angegeben"
        )
        lines.append(
            f"OCR-Text im Abruf: {'vorhanden' if data['content'] else 'nicht vorhanden'} · "
            f"OCR laut Abruf gekürzt: {truncated}."
        )
    return "\n".join(lines)


def paperless_evidence(
    job: AgentJob,
    profiles: dict[str, Any],
    history: list[AgentStep],
    *,
    max_bytes: int = 6000,
) -> str | None:
    """Render actual current sources/scope separately; do not alter a model answer.

    All relevant receipts are validated before output limiting. Any relevant
    failure, uncertain result, malformed receipt or revoked grant suppresses the
    entire block. Other jobs and legacy HTTP observations cannot supply evidence.
    """
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 10000:
        raise ValueError("Archive final-evidence budget is out of bounds")
    if job.cancel_requested:
        return None
    receipts = []
    try:
        seen = set()
        for step in history:
            if step.job_id != job.id or step.kind != "read":
                continue
            document = json.loads(step.document)
            if not isinstance(document, dict):
                return None
            if document.get("tool") != "paperless.read":
                continue
            if step.sequence in seen:
                return None
            seen.add(step.sequence)
            receipts.append(_receipt(job, profiles, step, document))
    except (KeyError, TypeError, ValueError, PermissionError, AttributeError):
        return None
    if not receipts:
        return None
    pieces = ["Quellen und Suchumfang (Paperless)"]
    included = 0
    for receipt in sorted(receipts, key=lambda item: item["sequence"]):
        for titles in (True, False):
            block = _block(receipt, titles=titles)
            candidate = "\n\n".join([*pieces, block, _FOOTER])
            # Reserve room for a truthful count of omitted later receipts.
            if len(candidate.encode()) + 120 <= max_bytes:
                pieces.append(block)
                included += 1
                break
        else:
            break
    if not included:
        return None
    if included < len(receipts):
        pieces.append(
            f"Ausgabegrenze: {len(receipts) - included} weitere gültige Abrufbelege ausgelassen."
        )
    pieces.append(_FOOTER)
    rendered = "\n\n".join(pieces)
    return rendered if len(rendered.encode()) <= max_bytes else None
