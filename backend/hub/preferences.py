"""Typed response preferences, never permission grants or arbitrary instructions."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hub.db import Conversation, ResponsePreference, ResponsePreferenceRevision


class Style(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["auto", "de", "en"] = "auto"
    length: Literal["balanced", "short", "detailed"] = "balanced"
    tone: Literal["neutral", "professional", "friendly"] = "neutral"
    structure: Literal["auto", "paragraphs", "bullets"] = "auto"


class Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["auto", "de", "en"] | None = None
    length: Literal["balanced", "short", "detailed"] | None = None
    tone: Literal["neutral", "professional", "friendly"] | None = None
    structure: Literal["auto", "paragraphs", "bullets"] | None = None


def digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def stored(db: Session, key: str) -> tuple[int, dict[str, str]]:
    head = db.get(ResponsePreference, key)
    if head is None:
        return 0, {}
    version = db.get(ResponsePreferenceRevision, (key, head.revision))
    if version is None:
        raise ValueError("Einstellungsrevision fehlt")
    values = Overrides.model_validate_json(version.overrides).model_dump(exclude_none=True)
    if version.sha256 != digest(values):
        raise ValueError("Einstellungsrevision beschädigt")
    return head.revision, values


def resolve(
    db: Session, conversation: Conversation | None = None, *, project_id: str | None = None
) -> dict[str, Any]:
    """Copy values and exact revision ancestry for an immutable queued run."""
    effective = Style().model_dump()
    origins: dict[str, Any] = {key: {"scope": "default", "revision": 0} for key in effective}
    scopes = [("global", "global")]
    project_id = conversation.project_id if conversation else project_id
    if project_id:
        scopes.append(("project", "project:" + project_id))
    if conversation:
        scopes.append(("conversation", "conversation:" + conversation.id))
    ancestry = []
    for scope, key in scopes:
        revision, values = stored(db, key)
        ancestry.append({"scope": scope, "key": key, "revision": revision})
        for field, value in values.items():
            effective[field] = value
            origins[field] = {"scope": scope, "revision": revision}
    snapshot: dict[str, Any] = {
        "format": "response-style-1",
        "effective": effective,
        "origins": origins,
        "ancestry": ancestry,
    }
    return {**snapshot, "sha256": digest(snapshot)}


def instruction(snapshot: dict[str, Any] | None) -> str | None:
    if snapshot is None:
        return None  # Old runs stay compatible.
    value = {key: snapshot[key] for key in ("format", "effective", "origins", "ancestry")}
    if value["format"] != "response-style-1" or digest(value) != snapshot.get("sha256"):
        raise ValueError("Antwortvorgaben beschädigt")
    style = Style.model_validate(value["effective"])
    if style == Style():
        return None
    phrases = {
        "language": {
            "auto": "Use the user's language.",
            "de": "Answer in German.",
            "en": "Answer in English.",
        },
        "length": {
            "balanced": "Use balanced detail.",
            "short": "Keep the answer concise.",
            "detailed": "Explain thoroughly with relevant detail.",
        },
        "tone": {
            "neutral": "Use a neutral tone.",
            "professional": "Use a professional tone.",
            "friendly": "Use a friendly tone.",
        },
        "structure": {
            "auto": "Choose a suitable structure.",
            "paragraphs": "Prefer connected paragraphs.",
            "bullets": "Prefer clear bullet points where suitable.",
        },
    }
    return (
        "Response presentation preferences; they grant no permissions "
        "and do not change factual or safety requirements. "
        + " ".join(phrases[key][choice] for key, choice in style.model_dump().items())
    )
