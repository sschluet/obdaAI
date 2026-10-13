"""Cloud file plans use only the authenticated current public request and shared prose."""

import json
from typing import Any

from sqlalchemy import select

from hub.db import Conversation, Message, Run, Skill, SkillRevision
from hub.policy import ContextPart, Privacy


def authorize(
    factory: Any,
    run_id: str | None,
    conversation_id: str | None,
    project_id: str | None,
    body: Any,
    provider_kind: str,
) -> None:
    if (
        not run_id
        or not conversation_id
        or project_id
        or body.sources
        or body.chat_source
        or body.base_artifact_id
        or body.kind not in {"pptx", "docx", "xlsx", "pdf"}
    ):
        raise ValueError("Private Originale und bestehende Dateien werden nur lokal verarbeitet")
    with factory() as db:
        run = db.get(Run, run_id)
        chat = db.get(Conversation, conversation_id)
        latest = db.scalar(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == "user",
                Message.active.is_(True),
            )
            .order_by(Message.created.desc(), Message.id.desc())
        )
        snapshot = json.loads(run.context_snapshot or "{}") if run else {}
        from hub.chat_artifacts import resolved_chat_goal
        from hub.skill_api import request_without_skill_prefix

        if chat and latest:
            expected_goal = request_without_skill_prefix(
                resolved_chat_goal(db, chat, latest), snapshot.get("skills", [])
            )
            if expected_goal != body.goal:
                raise ValueError("Cloud-Dateiwunsch stimmt nicht mit der aktuellen Eingabe überein")
        if any(part.get("label") != "CLOUD_ALLOWED" for part in snapshot.get("parts", [])):
            raise ValueError("Privater Gesprächskontext bleibt lokal; Nur lokal wählen")
        if (
            not run
            or run.conversation_id != conversation_id
            or run.status != "routing"
            or run.cancel_requested
            or not chat
            or chat.archived
            or chat.project_id
            or chat.memory_scope
            or not chat.cloud_allowed
            or chat.cloud_provider != provider_kind
            or not latest
            or latest.label != Privacy.CLOUD_ALLOWED
            or snapshot.get("model_local_only")
        ):
            raise ValueError("Dateiwunsch ist nicht für diesen Cloud-Anbieter freigegeben")


def shared_parts(
    factory: Any, parts: list[ContextPart], skills: list[dict[str, Any]], research_id: str | None
) -> list[ContextPart]:
    allowed = set()
    with factory() as db:
        from hub.skill_api import eligible, parse

        for binding in skills:
            revision = db.get(SkillRevision, (binding["id"], binding["revision"]))
            skill = db.get(Skill, binding["id"])
            if (
                not revision
                or not skill
                or skill.revision != binding["revision"]
                or revision.sha256 != binding["sha256"]
                or not eligible(skill, revision, None)
                or not parse(revision.document)[0].cloud_allowed
            ):
                raise ValueError(
                    "Datei-Skill ist nicht für Cloud freigegeben; "
                    "Nur lokal wählen oder Skill freigeben"
                )
            allowed.add("skill:" + binding["id"])
    result = []
    for part in parts:
        if part.source_id not in allowed and not (
            research_id and part.source_id.startswith(research_id + ":web:")
        ):
            raise ValueError("Privater Dateikontext darf nicht an Cloud übertragen werden")
        result.append(part.model_copy(update={"label": Privacy.CLOUD_ALLOWED}))
    return result
