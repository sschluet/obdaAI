"""Bound a frozen context without altering the saved conversation or its privacy."""

from typing import Any

from hub.db import Message
from hub.policy import ContextPart, Privacy


def recent_context(messages: list[Message], *, local_only: bool = False) -> dict[str, Any]:
    # Leave room within the existing 24k history boundary for a profile and
    # context annotations. Source and skill boundaries remain independently enforced.
    budget = 15700  # Reserve room for the optional privacy marker as well.
    selected: dict[str, str] = {}
    latest = messages[-1]
    selected[latest.id] = latest.content
    remaining = max(0, budget - len(latest.content.encode()) - 64)
    previous = messages[:-1]
    # Preserve the question behind the immediately preceding answer when possible,
    # then its tail: this supports an explicit continuation of a long partial answer.
    if previous and previous[-1].role == "assistant":
        assistant = previous[-1]
        question = next((m for m in reversed(previous[:-1]) if m.role == "user"), None)
        if question and len(question.content.encode()) + 64 <= remaining:
            selected[question.id] = question.content
            remaining -= len(question.content.encode()) + 64
        if remaining > 64:
            selected[assistant.id] = assistant.content.encode()[-(remaining - 64):].decode(
                "utf-8", errors="ignore"
            )
            remaining -= len(selected[assistant.id].encode()) + 64
    for message in reversed(previous):
        if message.id in selected:
            continue
        if len(selected) >= 39:
            break
        if len(message.content.encode()) + 64 <= remaining:
            selected[message.id] = message.content
            remaining -= len(message.content.encode()) + 64
    omitted = [m.id for m in messages if m.id not in selected]
    truncated = [
        {"id": m.id, "original_chars": len(m.content), "included_chars": len(selected[m.id])}
        for m in messages if m.id in selected and selected[m.id] != m.content
    ]
    parts, roles = [], []
    # Omitted private history must still block cloud processing of its derivatives.
    private_omitted = any(m.id not in selected and m.label == Privacy.LOCAL_ONLY for m in messages)
    if private_omitted:
        parts.append(ContextPart(
            content="Ältere geschützte Gesprächsteile sind außerhalb dieses Kontextfensters.",
            label=Privacy.LOCAL_ONLY, source_id="history-window:private", revision=1,
        ).model_dump(mode="json"))
        roles.append("system")
    for message in messages:
        if message.id in selected:
            parts.append(ContextPart(
                content=selected[message.id],
                label=Privacy.LOCAL_ONLY if local_only else Privacy(message.label),
                source_id=message.id, revision=message.revision,
            ).model_dump(mode="json"))
            roles.append(message.role)
    return {"parts": parts, "roles": roles, "context_window": {
        "omitted_message_ids": omitted, "truncated_messages": truncated,
        "private_history_retained": private_omitted, "byte_budget": budget,
    }}
