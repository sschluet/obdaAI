"""Local, read-only workspace discovery. Never return matched body text or configs."""

from typing import Annotated, Any, Literal
from typing import cast as typed_cast

from fastapi import Depends, FastAPI, Query
from sqlalchemy import JSON, case, cast, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from hub.auth import require_session
from hub.db import (
    Artifact,
    ArtifactRevision,
    Conversation,
    KnowledgeConnection,
    LoginSession,
    Message,
    Project,
    Source,
    Task,
    TaskRevision,
)

SearchKind = Literal["all", "conversation", "project", "artifact", "source", "task", "knowledge"]
LIMIT = 30


def install_workspace_search(app: FastAPI, factory: sessionmaker[Session]) -> None:
    @app.get("/api/workspace/search")
    def workspace_search(
        session: Annotated[LoginSession, Depends(require_session)],
        q: Annotated[str, Query(min_length=2, max_length=120)],
        kind: SearchKind = "all",
    ) -> dict[str, object]:
        query = q.strip()
        # Whitespace-only searches deliberately return nothing, never an inventory.
        if len(query) < 2:
            return {"query": query, "results": [], "has_more": False, "limit": LIMIT}
        pattern = (
            "%" + query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        results: list[dict[str, object]] = []
        with factory() as db:
            # SQLite lower() folds only ASCII. Match accented names consistently
            # with PostgreSQL without changing any stored workspace values.
            lower: Any = func.lower
            if db.get_bind().dialect.name == "sqlite":
                raw = typed_cast(Any, db.connection().connection.driver_connection)
                raw.create_function(
                    "workspace_lower",
                    1,
                    lambda value: value.lower() if isinstance(value, str) else value,
                    deterministic=True,
                )
                lower = func.workspace_lower

            def match(column: Any) -> Any:
                return lower(column).like(pattern, escape="\\")

            def json_field(column: Any, *keys: str) -> Any:
                if db.get_bind().dialect.name == "sqlite":
                    return func.json_extract(column, "$." + ".".join(keys))
                field: Any = cast(column, JSON)
                for key in keys:
                    field = field[key]
                return field.as_string()

            def collect(
                group: str, statement: Any, title: Any, content: Any, subtitle: str
            ) -> None:
                title_hit = match(title)
                statement = statement.where(or_(title_hit, content)).add_columns(title_hit)
                statement = statement.order_by(
                    case((title_hit, 0), else_=1), lower(title), statement.selected_columns[0]
                ).limit(LIMIT + 1)
                for item_id, item_title, project_id, hit in db.execute(statement):
                    results.append(
                        {
                            "kind": group,
                            "id": item_id,
                            "title": item_title,
                            "subtitle": subtitle,
                            "project_id": project_id,
                            "matched_in": "title" if hit else "content",
                        }
                    )

            if kind in ("all", "conversation"):
                body_hit = (
                    select(Message.id)
                    .where(
                        Message.conversation_id == Conversation.id,
                        Message.active.is_(True),
                        match(Message.content),
                    )
                    .exists()
                )
                parent_active = or_(
                    Conversation.project_id.is_(None),
                    select(Project.id)
                    .where(Project.id == Conversation.project_id, Project.archived.is_(False))
                    .exists(),
                )
                collect(
                    "conversation",
                    select(Conversation.id, Conversation.title, Conversation.project_id).where(
                        Conversation.archived.is_(False),
                        Conversation.purpose == "chat",
                        parent_active,
                    ),
                    Conversation.title,
                    body_hit,
                    "Gespräch",
                )
            if kind in ("all", "project"):
                collect(
                    "project",
                    select(Project.id, Project.name, Project.id).where(
                        Project.archived.is_(False), Project.kind == "project"
                    ),
                    Project.name,
                    match(Project.description),
                    "Projekt",
                )
            if kind in ("all", "source"):
                collect(
                    "source",
                    select(Source.id, Source.name, Source.project_id)
                    .join(Project)
                    .where(Project.archived.is_(False), Source.status != "superseded"),
                    Source.name,
                    False,
                    "Quelle",
                )
            if kind in ("all", "artifact"):
                title = json_field(ArtifactRevision.spec, "plan", "title")
                collect(
                    "artifact",
                    select(Artifact.id, title, Artifact.project_id)
                    .join(
                        ArtifactRevision,
                        (ArtifactRevision.artifact_id == Artifact.id)
                        & (ArtifactRevision.revision == Artifact.revision),
                    )
                    .join(Project)
                    .where(Project.archived.is_(False)),
                    title,
                    False,
                    "Datei",
                )
            if kind in ("all", "task"):
                title = json_field(TaskRevision.spec, "title")
                project_id = json_field(TaskRevision.spec, "project_id")
                parent_active = or_(
                    project_id.is_(None),
                    select(Project.id)
                    .where(Project.id == project_id, Project.archived.is_(False))
                    .exists(),
                )
                collect(
                    "task",
                    select(Task.id, title, project_id)
                    .join(
                        TaskRevision,
                        (TaskRevision.task_id == Task.id)
                        & (TaskRevision.revision == Task.revision),
                    )
                    .where(Task.archived.is_(False), parent_active),
                    title,
                    match(json_field(TaskRevision.spec, "goal")),
                    "Aufgabe",
                )
            if kind in ("all", "knowledge"):
                collect(
                    "knowledge",
                    select(
                        KnowledgeConnection.id,
                        KnowledgeConnection.name,
                        KnowledgeConnection.project_id,
                    ),
                    KnowledgeConnection.name,
                    match(KnowledgeConnection.kind),
                    "Wissensquelle",
                )
        results.sort(
            key=lambda result: (
                result["matched_in"] != "title",
                str(result["kind"]),
                str(result["title"]).lower(),
                str(result["id"]),
            )
        )
        return {
            "query": query,
            "results": results[:LIMIT],
            "has_more": len(results) > LIMIT,
            "limit": LIMIT,
        }
