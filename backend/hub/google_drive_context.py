"""Keep selected cached Drive sources bound to current authority at model dispatch."""

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.budgets import ExecutionLimitError
from hub.db import KnowledgeConnection, Project


def freeze_source(db: Session, project_id: str | None) -> dict[str, Any] | None:
    if not project_id:
        return None
    row = db.scalar(
        select(KnowledgeConnection).where(
            KnowledgeConnection.project_id == project_id,
            KnowledgeConnection.kind == "google_drive",
        )
    )
    if not row:
        return None
    return {
        "connection_id": row.id,
        "revision": row.revision,
        "project_id": project_id,
        "config_sha256": hashlib.sha256(row.config.encode()).hexdigest(),
    }


def check_source(factory: sessionmaker[Session], frozen: dict[str, Any]) -> None:
    from hub.google_drive_files import source_enabled

    with factory() as db:
        row = db.get(KnowledgeConnection, frozen["connection_id"])
        project = db.get(Project, frozen["project_id"])
        if (
            not row
            or row.kind != "google_drive"
            or not row.enabled
            or row.project_id != frozen["project_id"]
            or row.revision != frozen["revision"]
            or row.status not in {"ready", "partial"}
            or hashlib.sha256(row.config.encode()).hexdigest() != frozen["config_sha256"]
            or not project
            or project.archived
            or not source_enabled(db, row)
        ):
            raise ExecutionLimitError(
                "Google-Drive-Quelle geändert oder deaktiviert; Anfrage erneut starten"
            )
