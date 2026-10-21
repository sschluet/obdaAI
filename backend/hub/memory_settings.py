"""Authenticated controls and review of pointer-only learned memory proposals."""

import json
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput
from hub.config import Settings
from hub.db_locks import ownership_lock
from hub.knowledge_api import Auth
from hub.memory_models import MemoryCandidate, MemorySettings


class MemoryOptions(StrictInput):
    max_memories: int = Field(default=8, ge=0, le=20)
    max_context_chars: int = Field(default=6000, ge=0, le=16000)
    min_confidence: float = Field(default=0.85, ge=0, le=1, allow_inf_nan=False)
    review_required: bool = False
    learn_from_projects: bool = True
    sensitive_review_required: bool = True
    embedding_enabled: bool = False
    summary_enabled: bool = True
    extractor_provider_id: str | None = Field(default=None, max_length=36)


class MemorySettingsInput(StrictInput):
    revision: int = Field(ge=0)
    enabled: bool = True
    extraction_enabled: bool = True
    config: MemoryOptions = Field(default_factory=MemoryOptions)


class CandidateReview(StrictInput):
    expected_revision: int = Field(ge=1)
    decision: Literal["approve", "reject"]


def get_settings(db: Session) -> dict[str, Any]:
    row = db.get(MemorySettings, 1, populate_existing=True)
    if row is None:
        return MemorySettingsInput(revision=0).model_dump()
    return MemorySettingsInput(
        revision=row.revision,
        enabled=row.enabled,
        extraction_enabled=row.extraction_enabled,
        config=MemoryOptions.model_validate_json(row.config),
    ).model_dump()


def candidate_info(db: Session, row: MemoryCandidate) -> dict[str, Any]:
    from hub.memory_service import candidate_quote

    try:
        preview, fresh = candidate_quote(db, row), True
    except ValueError:
        preview, fresh = "", False
    value = {
        key: getattr(row, key)
        for key in (
            "id",
            "revision",
            "category",
            "fact_type",
            "subject",
            "predicate",
            "confidence",
            "sensitivity",
            "status",
            "source_message_id",
            "source_message_revision",
            "source_conversation_id",
            "source_sha256",
        )
    }
    return {**value, "preview": preview, "fresh": fresh}


def install_memory_settings_api(
    app: FastAPI, cfg: Settings, factory: sessionmaker[Session]
) -> None:
    @app.get("/api/memory-settings")
    def get(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return get_settings(db)

    @app.put("/api/memory-settings")
    def put(body: MemorySettingsInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            row = db.get(MemorySettings, 1)
            if (row.revision if row else 0) != body.revision:
                raise HTTPException(409, "Memory-Einstellungen inzwischen geändert")
            if row is None:
                row = MemorySettings(id=1)
                db.add(row)
            row.revision = body.revision + 1
            row.enabled, row.extraction_enabled = body.enabled, body.extraction_enabled
            # Sensitive review cannot be disabled via config or an extraction result.
            options = body.config.model_dump()
            options["sensitive_review_required"] = True
            row.config = json.dumps(options)
            db.commit()
            return get_settings(db)

    @app.get("/api/memory-candidates")
    def candidates(auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            return [
                candidate_info(db, row)
                for row in db.scalars(
                    select(MemoryCandidate)
                    .where(MemoryCandidate.owner_id == "owner", MemoryCandidate.status == "pending")
                    .order_by(MemoryCandidate.created.desc())
                    .limit(100)
                )
            ]

    @app.post("/api/memory-candidates/{candidate_id}/review")
    def review(candidate_id: str, body: CandidateReview, auth: Auth) -> dict[str, Any]:
        from hub.memory_service import memory_info, review_candidate

        with factory() as db:
            ownership_lock(db)
            try:
                row = review_candidate(
                    db,
                    candidate_id,
                    approve=body.decision == "approve",
                    expected_revision=body.expected_revision,
                )
                db.commit()
                return {
                    "candidate_id": candidate_id,
                    "status": "approved" if body.decision == "approve" else "rejected",
                    "memory": memory_info(row) if row else None,
                }
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
