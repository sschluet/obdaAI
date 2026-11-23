"""Factual document metadata answers from current validated search receipts."""

import json
from typing import Any

from hub.agent_intent import RequestIntent
from hub.agent_models import AgentJob, AgentStep
from hub.agent_paperless_evidence import _receipt, _text


def summary(
    job: AgentJob, profiles: dict[str, Any], history: list[AgentStep], *, max_bytes: int = 6000,
) -> str | None:
    """Requires a fresh caller gate; never reads targets or treats titles as instructions."""
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 10000:
        raise ValueError("Archive overview budget is out of bounds")
    try:
        intent = RequestIntent.model_validate(json.loads(job.bindings).get("intent"))
        if (intent.answer_kind != "document_inventory" or job.cancel_requested
                or len(profiles) != 1 or set(intent.target_ids) != set(profiles)
                or profiles[intent.target_ids[0]][0].kind != "paperless"):
            return None
        receipts = []
        for step in history:
            if step.job_id == job.id and (
                step.status in {"failed", "uncertain", "dispatching", "verifying"}
                or step.kind in {"effect", "verification"}
            ):
                return None
            if step.job_id != job.id or step.kind != "read":
                continue
            document = json.loads(step.document)
            if document.get("tool") != "paperless.read":
                return None
            receipt = _receipt(job, profiles, step, document)
            if receipt["result"]["operation"] != "search":
                return None  # Content/analysis is not answered by this metadata renderer.
            receipts.append(receipt)
        if not receipts:
            return None
    except (KeyError, ValueError, TypeError, AttributeError, PermissionError):
        return None
    lines = ["Beobachtete Dokumente (Metadaten)", ""]
    omitted = 0
    seen = set()
    for receipt in sorted(receipts, key=lambda row: row["sequence"]):
        data = receipt["result"]["data"]
        if lines[-1]:
            lines.append("")
        noun = "Dokument" if len(data["results"]) == 1 else "Dokumente"
        lines.append(
            f"Abruf {receipt['sequence']}: {len(data['results'])} {noun} auf Seite "
            f"{data['page']} gelesen; {data['count']} Treffer laut dieser Suchantwort."
        )
        lines.append("")
        if not data["results"]:
            lines.append("Keine Dokumente in dieser konkreten Suchantwort.")
        for row in data["results"]:
            key = (row["id"], row["title"])
            if key in seen:
                continue  # Preserve first-observed ordering; query totals stay separate.
            seen.add(key)
            line = f"- Dokument-ID {row['id']}: {_text(row['title'], 160)}"
            if len("\n".join([*lines, line]).encode()) + 200 <= max_bytes:
                lines.append(line)
            else:
                omitted += 1
    if omitted:
        lines.append("")
        lines.append(f"Ausgabegrenze: {omitted} weitere beobachtete Dokumenttitel ausgelassen.")
    lines.append("")
    lines.append("Dies ist eine begrenzte Metadatenübersicht; "
                 "Dokumentinhalte wurden nicht geprüft.")
    rendered = "\n".join(lines)
    return rendered if len(rendered.encode()) <= max_bytes else None
