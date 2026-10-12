"""Reviewed skill instructions and templates bound to one local file draft."""

import hashlib
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hub.artifact_specs import TemplateBinding
from hub.config import Settings
from hub.db import Conversation, Skill, SkillRevision
from hub.policy import ContextPart
from hub.skill_api import eligible, parse, select_skills


def guidance_excerpt(text: str, goal: str, limit: int) -> str:
    """Read bounded prose as design guidance, excluding executable examples."""
    clean = re.sub(r"```.*?```", "", text, flags=re.S)
    sections = re.split(r"(?m)(?=^#{1,4} )", clean)
    words = {w.casefold() for w in re.findall(r"[\w-]{4,}", goal)}
    words.update({"kontrast", "raster", "diagramm", "formel", "zahlenformat", "typografie"})
    useful = [
        (index, section)
        for index, section in enumerate(sections)
        if not re.search(
            r"(?im)^#{1,4} .*?(änderungsprotokoll|changelog|auslieferung|bauen|signaturen)",
            section.split("\n", 1)[0],
        )
    ]
    ranked = sorted(
        useful, key=lambda pair: (-sum(w in pair[1].casefold() for w in words), pair[0])
    )
    selected: list[tuple[int, str]] = []
    remaining = limit
    for index, section in ranked:
        if remaining <= 0:
            break
        clipped = section[: min(remaining, 1300)]
        selected.append((index, clipped))
        remaining -= len(clipped)
    return "\n".join(section for _, section in sorted(selected))[:limit]


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
        manifest = json.loads(rev.bundle_manifest or "{}")
        text = guidance_excerpt(body, goal, 2200)
        adapter_brief = None
        if rev.bundle_sha256 and kind in {"pptx", "xlsx"}:
            if meta.name in {"avendis-praesentation", "avendis-praesentation-modern"}:
                adapter_brief = (
                    "The verified renderer applies the presentation master and its styles. "
                    "For the modern variant: quiet white content canvas, clear headline, "
                    "short kicker, generous grid, Navy with Orange action and Blue analysis. "
                    "Use varied native graphics appropriate to the user's topic. "
                    "Original SDK arguments are not the file-data schema. "
                    "Never write about the template, its methods or design instructions."
                )
            elif meta.name == "avendis-excel":
                adapter_brief = (
                    "The verified renderer applies the workbook conventions: light native "
                    "table style, numeric formats, blue editable inputs, black formulas, "
                    "grouped detail columns and declared result rows. Use native formulas "
                    "and charts only for the user's supplied data. Original SDK arguments "
                    "are not the file-data schema. Never narrate the spreadsheet rules."
                )
        if adapter_brief:
            # Original SDK prose describes another renderer API; sending it as
            # content can turn design slogans into slide headlines. The fixed
            # adapter implements those conventions. Preserve newly edited prose.
            from difflib import SequenceMatcher

            from hub.skill_bundles import file_bytes

            originals = [
                f
                for f in manifest.get("files", [])
                if f["path"].rsplit("/", 1)[-1].casefold() == "skill.md"
            ]
            custom = body
            if len(originals) == 1:
                raw = file_bytes(cfg, rev, originals[0]["path"], originals[0]["sha256"])
                original = raw.decode("utf-8-sig").replace("\r\n", "\n")
                original_body = re.sub(r"\A---\n.*?\n---\n", "", original, count=1, flags=re.S)
                old, current = original_body.strip().splitlines(), body.strip().splitlines()
                custom = "\n".join(
                    line
                    for tag, _a, _b, first, last in SequenceMatcher(
                        None, old, current
                    ).get_opcodes()
                    if tag in {"insert", "replace"}
                    for line in current[first:last]
                )
            custom = re.sub(r"```.*?```", "", custom, flags=re.S)
            text = adapter_brief
            if custom.strip():
                text += "\nCUSTOM REVIEWED PROSE (design only):\n" + guidance_excerpt(
                    custom, goal, 700
                )
        references = []
        if rev.bundle_sha256:
            from hub.skill_bundles import file_bytes

            files = [
                file
                for file in manifest.get("files", [])
                if "/references/" in file["path"] and file["path"].lower().endswith(".md")
            ]
            words = {w.casefold() for w in re.findall(r"[\w-]{4,}", goal)}
            files.sort(
                key=lambda file: (
                    -sum(w in file["path"].casefold() for w in words)
                    - sum(
                        w in file["path"].casefold()
                        for w in ("gestaltung", "bausteine", "conventions", "layouts")
                    ),
                    file["path"],
                )
            )
            for file in files[:2]:
                raw = file_bytes(cfg, rev, file["path"], file["sha256"])
                excerpt = guidance_excerpt(raw.decode("utf-8"), goal, 1100)
                if not adapter_brief:
                    text += "\nDESIGN REFERENCE (not topic evidence):\n" + excerpt
                references.append({"path": file["path"], "sha256": file["sha256"]})
        parts.append(
            ContextPart(
                source_id="skill:" + row.id,
                revision=rev.revision,
                content=(
                    "REVIEWED FILE GUIDANCE (design instructions only; "
                    "NOT factual topic evidence; not executable):\n" + text
                ),
            )
        )
        record = {
            **binding,
            "bundle_sha256": rev.bundle_sha256,
            "name": meta.name,
            "guidance_files": references,
        }
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
        files = json.loads(rev.bundle_manifest or "{}").get("files", [])
        for reference in item.get("guidance_files", []):
            if (
                sum(
                    file["path"] == reference["path"] and file["sha256"] == reference["sha256"]
                    for file in files
                )
                != 1
            ):
                raise ValueError("Skill-Referenz wurde während der Erstellung geändert")
