"""Reviewed skill instructions and templates bound to one local file draft."""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hub.artifact_specs import TemplateBinding
from hub.config import Settings
from hub.db import Conversation, Skill, SkillRevision
from hub.policy import ContextPart
from hub.skill_api import eligible, parse, select_skills


def chosen(db: Session, chat: Conversation, goal: str) -> list[dict[str, Any]]:
    _, audit = select_skills(db, chat, goal)
    return [
        {"id": item["id"], "revision": item["revision"], "sha256": item["sha256"]} for item in audit
    ]


def context(
    db: Session,
    cfg: Settings,
    project_id: str | None,
    bindings: list[dict[str, Any]],
    kind: str,
    goal: str,
) -> tuple[list[ContextPart], TemplateBinding | None, list[dict[str, Any]]]:
    from hub.skill_bundles import resolve_template

    parts: list[ContextPart] = []
    records: list[dict[str, Any]] = []
    candidates: list[tuple[Any, Any, Any]] = []
    modern = False
    bindings = list(bindings)
    # Dependencies are resolved only for an explicitly selected active package.
    for binding in list(bindings):
        row = db.get(Skill, binding["id"])
        revision = db.get(SkillRevision, (binding["id"], binding["revision"]))
        if not row or not revision or not eligible(row, revision, project_id):
            raise ValueError(
                "Datei-Skill ist nicht mehr aktiv oder gehört zu einem anderen Projekt"
            )
        meta, _ = parse(revision.document)
        if meta.name == "avendis-praesentation-modern":
            modern = True
            bases = []
            for candidate in db.scalars(select(Skill)):
                rev = db.get(SkillRevision, (candidate.id, candidate.revision))
                if (
                    rev
                    and eligible(candidate, rev, project_id)
                    and parse(rev.document)[0].name == "avendis-praesentation"
                ):
                    bases.append((candidate, rev))
            if len(bases) != 1:
                raise ValueError(
                    "Moderne Präsentationen benötigen genau einen aktivierten Basis-Skill"
                )
            base, rev = bases[0]
            if not any(item["id"] == base.id for item in bindings):
                bindings.append({"id": base.id, "revision": rev.revision, "sha256": rev.sha256})
    if len(bindings) > 3:
        raise ValueError("Höchstens drei Datei-Skills auswählen")
    for binding in bindings:
        row = db.get(Skill, binding["id"])
        rev = db.get(SkillRevision, (binding["id"], binding["revision"]))
        if (
            not row
            or not rev
            or row.revision != binding["revision"]
            or rev.sha256 != binding["sha256"]
            or not eligible(row, rev, project_id)
        ):
            raise ValueError("Geprüfte Skill-Version wurde inzwischen geändert")
        meta, body = parse(rev.document)
        # The full original remains available in the library. Only task-specific
        # guidance enters this bounded local data-plan request; code stays data.
        from hub.skill_api import instruction_context

        text = instruction_context(meta, body, json.loads(rev.bundle_manifest or "{}"), goal)
        parts.append(
            ContextPart(
                source_id="skill:" + row.id,
                revision=rev.revision,
                content="REVIEWED FILE GUIDANCE (not executable):\n" + text,
            )
        )
        record = {**binding, "bundle_sha256": rev.bundle_sha256, "name": meta.name}
        records.append(record)
        if rev.bundle_sha256:
            manifest = json.loads(rev.bundle_manifest or "{}")
            for file in manifest.get("files", []):
                suffix = file["path"].rsplit(".", 1)[-1].lower()
                if suffix in (
                    {"docx", "dotx"}
                    if kind == "docx"
                    else {"pptx", "potx"}
                    if kind == "pptx"
                    else set()
                ):
                    candidates.append((row, rev, file))
    if len(candidates) > 1:
        # A letter and a report template cannot silently replace one another.
        raise ValueError("Mehrere Vorlagen ausgewählt; genau einen passenden Datei-Skill wählen")
    template = None
    if candidates:
        row, rev, asset = candidates[0]
        resolve_template(db, cfg, row.id, rev.revision, rev.bundle_sha256, asset["path"])
        template = TemplateBinding(
            skill_id=row.id,
            revision=rev.revision,
            bundle_sha256=rev.bundle_sha256,
            asset_path=asset["path"],
            asset_sha256=asset["sha256"],
            style="modern" if modern else "base",
        )
    return parts, template, records


def verify(db: Session, project_id: str | None, records: list[dict[str, Any]]) -> None:
    for item in records:
        row = db.get(Skill, item["id"])
        rev = db.get(SkillRevision, (item["id"], item["revision"]))
        if (
            not row
            or not rev
            or row.revision != item["revision"]
            or not eligible(row, rev, project_id)
            or rev.sha256 != item["sha256"]
            or rev.bundle_sha256 != item.get("bundle_sha256")
        ):
            raise ValueError("Datei-Skill wurde während der Erstellung geändert")
        if hashlib.sha256(rev.document.encode()).hexdigest() != rev.sha256:
            raise ValueError("Skill-Anleitung wurde verändert")
