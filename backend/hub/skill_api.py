"""Bounded portable skill instructions; revision-bound review, never executable tools."""

import hashlib
import json
import re
import unicodedata
from typing import Any, Literal
from urllib.parse import unquote
from uuid import UUID

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput
from hub.config import Settings
from hub.db import Conversation, Project, Run, Skill, SkillRevision
from hub.db_locks import ownership_lock
from hub.knowledge_api import Auth
from hub.policy import ContextPart, Privacy


class Metadata(StrictInput):
    format: str = Field(pattern=r"^obdaai-skill-1$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    usage: Literal["auto", "always", "mention"] = "auto"
    cloud_allowed: bool = False


class SkillInput(StrictInput):
    document: str = Field(min_length=1, max_length=64000)
    project_id: UUID | None = None
    activate: bool = False
    expected_revision: int | None = Field(default=None, ge=1)


class TrustInput(StrictInput):
    expected_revision: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    enabled: bool


class SelectionInput(StrictInput):
    skill_ids: list[UUID] | None = Field(default=None, max_length=3)
    expected_selection: list[UUID] | None = Field(default=None, max_length=3)


class ImportInput(StrictInput):
    document: str = Field(min_length=1, max_length=64000)
    name: str | None = Field(default=None, min_length=1, max_length=100)


class ArchiveInput(StrictInput):
    expected_revision: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:100]


def request_without_skill_prefix(query: str, audit: list[dict[str, Any]]) -> str:
    """Interpret the user's request after exact, already-selected invocations.

    This is only intent normalization. Stored messages and authorized public
    queries remain unchanged; arbitrary slash commands are never removed.
    """
    names = [slug(item["name"]) for item in audit if isinstance(item.get("name"), str)]
    if not names:
        return query
    pattern = r"^\s*[/@](?:" + "|".join(re.escape(name) for name in names) + r")(?:\s+|$)"
    while match := re.match(pattern, query, re.I):
        query = query[match.end() :]
    return query


def parse(document: str) -> tuple[Metadata, str]:
    try:
        document = document.replace("\r\n", "\n")
        if len(document) > 64000 or not document.startswith("---\n"):
            raise ValueError
        front, body = document[4:].split("\n---\n", 1)
        # Reject aliases, anchors and explicit tags before construction; safe_load
        # never imports executable Python objects. One bounded mapping only.
        tokens = list(yaml.scan(front))
        if any(
            isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken, yaml.tokens.TagToken))
            for t in tokens
        ):
            raise ValueError
        depth = 0
        starts = (
            yaml.tokens.BlockMappingStartToken,
            yaml.tokens.BlockSequenceStartToken,
            yaml.tokens.FlowMappingStartToken,
            yaml.tokens.FlowSequenceStartToken,
        )
        ends = (
            yaml.tokens.BlockEndToken,
            yaml.tokens.FlowMappingEndToken,
            yaml.tokens.FlowSequenceEndToken,
        )
        for token in tokens:
            if isinstance(token, starts):
                depth += 1
                if depth > 12:
                    raise ValueError
            elif isinstance(token, ends):
                depth -= 1
        data = yaml.safe_load(front)
        if not isinstance(data, dict):
            raise ValueError
        if "format" not in data:
            if not isinstance(data.get("description"), str) or not data["description"].strip():
                raise ValueError
            data = {"format": "obdaai-skill-1", **data}
        meta = Metadata.model_validate(data)
        if (
            not meta.name.strip()
            or not slug(meta.name)
            or not body.strip()
            or any(not k.strip() or len(k) > 80 for k in meta.keywords)
        ):
            raise ValueError
        return meta, body.strip()
    except (ValueError, ValidationError, yaml.YAMLError):
        raise HTTPException(
            422,
            "Skill braucht Name, gültiges YAML-/JSON-Frontmatter "
            "und Markdown-Inhalt; Werkzeuge werden nicht importiert",
        ) from None


def portable(meta: Metadata, body: str) -> str:
    return "---\n" + json.dumps(meta.model_dump(), ensure_ascii=False, indent=2) + "\n---\n" + body


def sha(document: str) -> str:
    return hashlib.sha256(document.encode()).hexdigest()


def lock(db: Session) -> None:
    ownership_lock(db)
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.execute(text("SELECT pg_advisory_xact_lock(791103044)"))


def get(db: Session, skill_id: str) -> tuple[Skill, SkillRevision]:
    s = db.get(Skill, skill_id)
    if s is None:
        raise HTTPException(404, "Skill fehlt")
    r = db.get(SkillRevision, (s.id, s.revision))
    if r is None or r.sha256 != sha(r.document):
        raise HTTPException(409, "Skillrevision beschädigt")
    return s, r


def info(s: Skill, r: SkillRevision) -> dict[str, Any]:
    return {
        "id": s.id,
        "revision": r.revision,
        "sha256": r.sha256,
        "document": r.document,
        "bundle_sha256": r.bundle_sha256,
        "bundle_manifest": json.loads(r.bundle_manifest),
        "project_id": s.project_id,
        "invocation": "/" + slug(parse(r.document)[0].name),
        "archived": s.archived,
        "enabled": s.enabled,
        "trusted": s.trusted_sha256 == r.sha256,
        **parse(r.document)[0].model_dump(),
    }


def eligible(s: Skill, r: SkillRevision, project_id: str | None) -> bool:
    return (
        s.enabled
        and not s.archived
        and s.trusted_sha256 == r.sha256
        and r.sha256 == sha(r.document)
        and s.project_id in (None, project_id)
    )


def instruction_context(meta: Metadata, body: str, manifest: dict[str, Any], query: str) -> str:
    """Bounded instruction excerpt; full original remains available in the package."""
    clean = re.sub(r"```.*?```", "", body, flags=re.S)
    if len(clean) <= 6000:
        return clean
    words = {w.casefold() for w in re.findall(r"[\w-]{4,}", query)}
    sections = re.split(r"(?m)(?=^#{1,4} )", clean)
    ranked = sorted(
        enumerate(sections),
        key=lambda pair: (-sum(w in pair[1].casefold() for w in words), pair[0]),
    )
    chosen = [(0, sections[0][:1800])]
    left = 5600 - len(chosen[0][1])
    for index, section in ranked:
        if index == 0 or left <= 0:
            continue
        clipped = section[:left]
        chosen.append((index, clipped))
        left -= len(clipped)
    return (
        "\n".join(s for _, s in sorted(chosen))
        + "\n[Auszug aus Skillpaket; vollständige Anweisungen und Vorlagen separat verfügbar.]"
    )


def select_skills(
    db: Session, chat: Conversation, query: str
) -> tuple[list[ContextPart], list[dict[str, Any]]]:
    selected = json.loads(chat.skill_selection) if chat.skill_selection is not None else None
    rows = list(db.scalars(select(Skill).order_by(Skill.id)))
    parts: list[ContextPart] = []
    audit: list[dict[str, Any]] = []
    invocation_names: dict[str, list[str]] = {}
    for candidate in rows:
        rev = db.get(SkillRevision, (candidate.id, candidate.revision))
        if rev and eligible(candidate, rev, chat.project_id):
            invocation_names.setdefault(slug(parse(rev.document)[0].name), []).append(candidate.id)
    mentions = set(
        re.findall(r"(?<![\w/@])[/@]([a-z0-9]+(?:-[a-z0-9]+)*)(?![\w/@-]|\.[\w])", query.casefold())
    )
    if selected is None and any(len(invocation_names.get(m, [])) > 1 for m in mentions):
        raise HTTPException(409, "Skill-Aufruf mehrdeutig; Namen unterscheiden oder manuell wählen")
    for s in rows:
        if selected is not None and s.id not in selected:
            continue
        r = db.get(SkillRevision, (s.id, s.revision))
        if r is None or not eligible(s, r, chat.project_id):
            if selected is not None:
                raise HTTPException(
                    409,
                    "Ausgewählter Skill nicht mehr aktiviert/vertraut oder außerhalb des Projekts",
                )
            continue
        meta, body = parse(r.document)
        mentioned = slug(meta.name) in mentions
        keyword = meta.usage == "auto" and any(
            k.casefold() in query.casefold() for k in meta.keywords
        )
        if selected is None and not (mentioned or meta.usage == "always" or keyword):
            continue
        label = Privacy.CLOUD_ALLOWED if meta.cloud_allowed else Privacy.LOCAL_ONLY
        if len(parts) == 3:
            raise HTTPException(409, "Mehr als drei passende Skills; manuelle Auswahl nötig")
        parts.append(
            ContextPart(
                content="Vom Benutzer geprüfter Skill: "
                + meta.name
                + "\n"
                + (
                    instruction_context(meta, body, json.loads(r.bundle_manifest), query)
                    if r.bundle_sha256
                    else body
                ),
                source_id="skill:" + s.id,
                revision=r.revision,
                label=label,
            )
        )
        audit.append(
            {
                "id": s.id,
                "name": meta.name,
                "revision": r.revision,
                "sha256": r.sha256,
                "selection": (
                    "manual"
                    if selected is not None
                    else "mention"
                    if mentioned
                    else "always"
                    if meta.usage == "always"
                    else "keyword"
                ),
                "usage": meta.usage,
                "label": label.value,
            }
        )
    if selected is not None and len(parts) != len(selected):
        raise HTTPException(409, "Ausgewählter Skill fehlt")
    for entry in list(audit):
        revision = db.get(SkillRevision, (entry["id"], entry["revision"]))
        dependencies = (
            json.loads(revision.bundle_manifest).get("dependencies", []) if revision else []
        )
        for dependency in dependencies:
            if any(item["name"] == dependency for item in audit):
                continue
            matches = []
            for candidate in rows:
                candidate_revision = db.get(SkillRevision, (candidate.id, candidate.revision))
                if candidate_revision and eligible(candidate, candidate_revision, chat.project_id):
                    candidate_meta, candidate_body = parse(candidate_revision.document)
                    if candidate_meta.name == dependency:
                        matches.append(
                            (candidate, candidate_revision, candidate_meta, candidate_body)
                        )
            if len(matches) != 1 or len(parts) >= 3:
                raise HTTPException(
                    409, "Skill-Abhängigkeit fehlt, ist nicht geprüft oder mehrdeutig"
                )
            candidate, candidate_revision, candidate_meta, candidate_body = matches[0]
            label = Privacy.CLOUD_ALLOWED if candidate_meta.cloud_allowed else Privacy.LOCAL_ONLY
            parts.append(
                ContextPart(
                    content="Vom Benutzer geprüfter Basis-Skill: "
                    + candidate_meta.name
                    + "\n"
                    + instruction_context(
                        candidate_meta,
                        candidate_body,
                        json.loads(candidate_revision.bundle_manifest),
                        query,
                    ),
                    source_id="skill:" + candidate.id,
                    revision=candidate_revision.revision,
                    label=label,
                )
            )
            audit.append(
                {
                    "id": candidate.id,
                    "name": candidate_meta.name,
                    "revision": candidate_revision.revision,
                    "sha256": candidate_revision.sha256,
                    "selection": "dependency",
                    "usage": candidate_meta.usage,
                    "label": label.value,
                }
            )
    return parts, audit


def install_skill_api(
    app: FastAPI, factory: sessionmaker[Session], cfg: Settings | None = None
) -> None:
    cfg = cfg or Settings()

    @app.post("/api/skills/import-package")
    async def import_package(request: Request, auth: Auth) -> dict[str, Any]:
        from hub.skill_bundles import MAX_PACKAGE, inspect_package, store

        name = unquote(request.headers.get("X-File-Name", ""))
        if not name.lower().endswith((".zip", ".skill")):
            raise HTTPException(422, "Skillpaket als .zip oder .skill hochladen")
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > MAX_PACKAGE:
                raise HTTPException(413, "Skillpaket maximal 20 MiB")
        content = bytes(chunks)
        document, manifest = inspect_package(content)
        bundle_sha = store(cfg, content)
        with factory() as db:
            lock(db)
            skill = Skill(enabled=False)
            db.add(skill)
            db.flush()
            revision = SkillRevision(
                skill_id=skill.id,
                revision=1,
                document=document,
                sha256=sha(document),
                bundle_sha256=bundle_sha,
                bundle_manifest=json.dumps(manifest),
            )
            db.add(revision)
            db.commit()
            return info(skill, revision)

    def bundle_revision(db: Session, skill_id: str, revision: int) -> SkillRevision:
        get(db, skill_id)
        item = db.get(SkillRevision, (skill_id, revision))
        if item is None or item.sha256 != sha(item.document):
            raise HTTPException(404, "Skillrevision fehlt")
        return item

    @app.get("/api/skills/{skill_id}/revisions/{revision}/files")
    def download_file(skill_id: str, revision: int, path: str, sha256: str, auth: Auth) -> Response:
        from hub.skill_bundles import file_bytes

        with factory() as db:
            content = file_bytes(cfg, bundle_revision(db, skill_id, revision), path, sha256)
        return Response(
            content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment", "Cache-Control": "no-store"},
        )

    @app.get("/api/skills/{skill_id}/revisions/{revision}/package")
    def download_package(skill_id: str, revision: int, sha256: str, auth: Auth) -> Response:
        from hub.skill_bundles import package_bytes

        with factory() as db:
            item = bundle_revision(db, skill_id, revision)
            if item.bundle_sha256 != sha256:
                raise HTTPException(409, "Paketrevision inzwischen geändert")
            content = package_bytes(cfg, item)
        return Response(
            content,
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=skill-package.zip",
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/skills/parse")
    def import_document(body: ImportInput, auth: Auth) -> dict[str, Any]:
        raw = body.document.replace("\r\n", "\n")
        if not raw.startswith("---\n"):
            if not body.name:
                raise HTTPException(422, "Für Markdown ohne Frontmatter einen Namen angeben")
            meta = Metadata(format="obdaai-skill-1", name=body.name, usage="mention")
            raw = portable(meta, raw)
        meta, content = parse(raw)
        # An imported cloud flag never silently becomes outbound permission.
        meta.cloud_allowed = False
        return {
            **meta.model_dump(),
            "body": content,
            "document": portable(meta, content),
            "invocation": "/" + slug(meta.name),
        }

    @app.get("/api/skills")
    def listing(auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            return [
                info(*get(db, s.id))
                for s in db.scalars(
                    select(Skill).where(Skill.archived.is_(False)).order_by(Skill.id)
                )
            ]

    @app.post("/api/skills")
    def create(body: SkillInput, auth: Auth) -> dict[str, Any]:
        parse(body.document)
        with factory() as db:
            lock(db)
            if body.project_id is not None and not db.get(Project, str(body.project_id)):
                raise HTTPException(404, "Projekt fehlt")
            s = Skill(
                project_id=str(body.project_id) if body.project_id else None,
                enabled=body.activate,
                trusted_sha256=sha(body.document) if body.activate else None,
            )
            db.add(s)
            db.flush()
            r = SkillRevision(
                skill_id=s.id, revision=1, document=body.document, sha256=sha(body.document)
            )
            db.add(r)
            db.commit()
            return info(s, r)

    @app.patch("/api/skills/{skill_id}")
    def edit(skill_id: str, body: SkillInput, auth: Auth) -> dict[str, Any]:
        parse(body.document)
        with factory() as db:
            lock(db)
            s, previous = get(db, skill_id)
            if s.archived:
                raise HTTPException(409, "Archivierter Skill kann nicht bearbeitet werden")
            if s.revision != body.expected_revision:
                raise HTTPException(409, "Skill inzwischen geändert; Entwurf bleibt erhalten")
            if body.project_id is not None and not db.get(Project, str(body.project_id)):
                raise HTTPException(404, "Projekt fehlt")
            s.revision += 1
            s.enabled = body.activate
            s.trusted_sha256 = sha(body.document) if body.activate else None
            s.project_id = str(body.project_id) if body.project_id else None
            r = SkillRevision(
                skill_id=s.id,
                revision=s.revision,
                document=body.document,
                sha256=sha(body.document),
                bundle_sha256=previous.bundle_sha256,
                bundle_manifest=previous.bundle_manifest,
            )
            db.add(r)
            db.commit()
            return info(s, r)

    @app.post("/api/skills/{skill_id}/trust")
    def trust(skill_id: str, body: TrustInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            s, r = get(db, skill_id)
            if s.archived or s.revision != body.expected_revision or r.sha256 != body.sha256:
                raise HTTPException(
                    409, "Nur die genau geprüfte Skillrevision kann aktiviert werden"
                )
            s.enabled = body.enabled
            s.trusted_sha256 = r.sha256 if body.enabled else None
            db.commit()
            return info(s, r)

    @app.delete("/api/skills/{skill_id}")
    def archive(skill_id: str, body: ArchiveInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            s, r = get(db, skill_id)
            if s.revision != body.expected_revision or r.sha256 != body.sha256:
                raise HTTPException(409, "Skill inzwischen geändert; vor Entfernen neu laden")
            s.archived = True
            s.enabled = False
            s.trusted_sha256 = None
            db.commit()
            return info(s, r)

    @app.get("/api/skills/{skill_id}/revisions")
    def revisions(skill_id: str, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            get(db, skill_id)
            return [
                {
                    "revision": r.revision,
                    "sha256": r.sha256,
                    "document": r.document,
                    "bundle_sha256": r.bundle_sha256,
                    "bundle_manifest": json.loads(r.bundle_manifest),
                }
                for r in db.scalars(
                    select(SkillRevision)
                    .where(SkillRevision.skill_id == skill_id)
                    .order_by(SkillRevision.revision)
                )
            ]

    @app.get("/api/conversations/{chat_id}/skills")
    def selection(chat_id: str, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            c = db.get(Conversation, chat_id)
            if not c or c.purpose != "chat":
                raise HTTPException(404, "Gespräch fehlt")
            return {
                "skill_ids": json.loads(c.skill_selection)
                if c.skill_selection is not None
                else None
            }

    @app.patch("/api/conversations/{chat_id}/skills")
    def change_selection(chat_id: str, body: SelectionInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            c = db.scalar(select(Conversation).where(Conversation.id == chat_id).with_for_update())
            if not c or c.purpose != "chat" or c.archived:
                raise HTTPException(404, "Aktives Gespräch fehlt")
            old = json.loads(c.skill_selection) if c.skill_selection is not None else None
            expected = (
                [str(x) for x in body.expected_selection]
                if body.expected_selection is not None
                else None
            )
            if old != expected:
                raise HTTPException(409, "Skillauswahl inzwischen geändert")
            if db.scalar(
                select(Run.id).where(
                    Run.conversation_id == chat_id,
                    Run.status.in_(["queued", "routing", "streaming"]),
                )
            ):
                raise HTTPException(409, "Laufendes Gespräch; Auswahl danach ändern")
            ids = [str(x) for x in body.skill_ids] if body.skill_ids is not None else None
            if ids is not None:
                if len(ids) != len(set(ids)):
                    raise HTTPException(422, "Skill doppelt ausgewählt")
                for sid in ids:
                    if not eligible(*get(db, sid), c.project_id):
                        raise HTTPException(409, "Skill nicht verfügbar für dieses Gespräch")
            c.skill_selection = json.dumps(ids) if ids is not None else None
            db.commit()
            return {"skill_ids": ids}
