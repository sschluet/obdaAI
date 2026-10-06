"""Explicit project-chat file requests use the same bounded artifact service."""

import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hub.artifact_api import CreateArtifact, artifact_service
from hub.artifact_drafts import DraftInput, preview
from hub.artifact_specs import ArtifactSpec, SourceBinding
from hub.artifacts import digest, spec_for
from hub.db import Artifact, ArtifactRevision, Conversation, Message, Run, Source


def requests_revision(goal: str) -> bool:
    return bool(re.search(r"\b(überarbeite|ändere|kürze|revise|shorten|update)\b", goal, re.I))


def explicit_revision_target(goal: str) -> bool:
    name = (
        r"(?:word[- ](?:datei|dokument|file|document)|worddatei|worddokument|"
        r"powerpoint(?:[- ](?:datei|file))?|präsentation|datei|version|dokument|"
        r"docx|pptx|pdf|file|presentation|document)"
    )
    where = r"(?:\s+(?:hier|in\s+diesem\s+gespräch))?"
    made = r"(?:erzeugte[nrs]?|erstellte[nrs]?)"
    last = (
        r"(?:letzte[nrs]?"
        + where
        + r"(?:\s+"
        + made
        + r")?|zuletzt"
        + where
        + r"\s+"
        + made
        + r"|(?:last|latest)(?:\s+(?:created|generated))?)"
    )
    action = r"^\s*(?:(?:bitte|please)\s+)?(?:überarbeite|ändere|kürze|revise|shorten|update)\s+"
    target = (
        r"(?:(?:(?:die|das|the)\s+)?"
        + last
        + r"\s+"
        + name
        + r"|(?:folie|slide)\s+\d{1,3}\s+(?:der|(?:of|in)(?:\s+the)?)\s+"
        + last
        + r"\s+"
        + name
        + r")\b"
    )
    return bool(
        re.search(action + target, goal, re.I)
        or re.fullmatch(
            r"(?:kürze|überarbeite|shorten|revise)\s+(?:folie|slide)\s+\d{1,3}[.!]?",
            goal.strip(),
            re.I,
        )
    )


def chat_base(db: Session, chat_id: str, project_id: str, run: Run) -> ArtifactRevision:
    # Only a file linked by a successful run in this exact conversation. Neither
    # arbitrary project files nor model-selected IDs establish an editing target.
    previous = db.scalars(
        select(Run)
        .where(
            Run.conversation_id == chat_id,
            Run.status == "succeeded",
            Run.id != run.id,
            Run.started <= run.started,
        )
        .order_by(Run.started.desc(), Run.id.desc())
        .limit(50)
    )
    for earlier in previous:
        link = json.loads(earlier.context_snapshot or "{}").get("artifact")
        if not link:
            continue
        artifact = db.get(Artifact, link["artifact_id"])
        row = db.get(ArtifactRevision, (link["artifact_id"], link["revision"]))
        if (
            link["project_id"] != project_id
            or not artifact
            or artifact.project_id != project_id
            or not row
            or row.revision != artifact.revision
            or row.status in {"failed", "cancelled"}
            or spec_for(row).plan.kind != link["kind"]
        ):
            raise ValueError(
                "Letzte Chat-Datei ist nicht mehr aktuell; Version im Dateidialog wählen"
            )
        return row
    raise ValueError("In diesem Gespräch fehlt eine konkrete Datei für die Änderung")


def requests_project_sources(goal: str) -> bool:
    """Only an explicit request for this project's complete document collection."""
    names = r"(?:projektunterlagen|projektdokumente(?:n)?|projektquellen|project documents)"
    positive = re.search(r"\b(?:aus|anhand|from|using)\b.{0,50}\b" + names + r"\b", goal, re.I)
    negative = re.search(
        r"\b(?:keine|ohne|nicht|no|without)\b.{0,25}\b" + names + r"\b", goal, re.I
    )
    if positive and negative:
        raise ValueError("Quellenauswahl ist widersprüchlich; Quellen im Dateidialog auswählen")
    return bool(positive)


def request_format(goal: str, default_slide_count: int = 3) -> tuple[str, int]:
    if not requests_revision(goal) and not re.search(
        r"\b(erstelle|erzeuge|generiere|schreibe|create|generate|make)\b", goal, re.I
    ):
        raise ValueError("Eine konkrete Bitte zur Dateierstellung fehlt")
    formats = []
    for kind, pattern in [
        ("docx", r"\b(word|docx)\b"),
        ("pptx", r"\b(powerpoint|pptx|präsentation|presentation)\b"),
        ("pdf", r"\bpdf\b"),
    ]:
        if re.search(pattern, goal, re.I):
            formats.append(kind)
    if len(formats) != 1:
        raise ValueError("Ein Dateiformat auswählen: Word, PowerPoint oder PDF")
    words = {
        "eine": 1,
        "eins": 1,
        "zwei": 2,
        "drei": 3,
        "vier": 4,
        "fünf": 5,
        "sechs": 6,
        "sieben": 7,
        "acht": 8,
        "neun": 9,
        "zehn": 10,
        "elf": 11,
        "zwölf": 12,
        "dreizehn": 13,
        "vierzehn": 14,
        "fünfzehn": 15,
        "sechzehn": 16,
        "siebzehn": 17,
        "achtzehn": 18,
        "neunzehn": 19,
        "zwanzig": 20,
        "einundzwanzig": 21,
        "zweiundzwanzig": 22,
        "dreiundzwanzig": 23,
        "vierundzwanzig": 24,
        "fünfundzwanzig": 25,
        "sechsundzwanzig": 26,
        "siebenundzwanzig": 27,
        "achtundzwanzig": 28,
        "neunundzwanzig": 29,
        "dreißig": 30,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    counts = re.findall(r"\b(\d{1,3})\s*(?:folien|slides)\b", goal, re.I)
    for word in re.findall(r"\b([a-zäöüß]+)\s+(?:folien|slides)\b", goal.casefold()):
        if word in words:
            counts.append(str(words[word]))
        elif word not in {"mit", "den", "die", "the", "editierbare", "editable"}:
            raise ValueError("Folienanzahl bitte eindeutig als Zahl von 1 bis 30 angeben")
    if len(set(counts)) > 1 or (counts and not 1 <= int(counts[0]) <= 30):
        raise ValueError("Eine eindeutige Anzahl von 1 bis 30 Folien angeben")
    return formats[0], int(counts[0]) if counts else default_slide_count


async def create_from_chat(
    factory: Any, cfg: Any, run_id: str, provider: Any = None
) -> dict[str, Any]:
    with factory() as db:
        run = db.get(Run, run_id)
        if not run:
            raise ValueError("Dateilauf fehlt")
        chat = db.get(Conversation, run.conversation_id)
        message = db.scalar(
            select(Message)
            .where(
                Message.conversation_id == run.conversation_id,
                Message.role == "user",
                Message.active.is_(True),
            )
            .order_by(Message.created.desc(), Message.id.desc())
        )
        if not chat or not chat.project_id or chat.memory_scope or chat.archived or not message:
            raise ValueError("Dateien im aktiven Projektgespräch erstellen")
        project_id, chat_id, message_id = chat.project_id, chat.id, message.id
        revision, goal, sha = message.revision, message.content, digest(message.content)
        if len(goal) > 4000:
            raise ValueError("Dateiwunsch darf höchstens 4000 Zeichen enthalten")
        revising = requests_revision(goal)
        if revising and not explicit_revision_target(goal):
            raise ValueError(
                "Die letzte Chat-Datei ausdrücklich benennen oder eine konkrete Version "
                "im Dateidialog wählen; es wurde keine Datei geändert"
            )
        base = chat_base(db, chat_id, project_id, run) if revising else None
        original = spec_for(base) if base else None
        sources = list(original.sources) if original else []
        if requests_project_sources(goal):
            originals = list(db.scalars(select(Source).where(Source.project_id == project_id)))
            if not originals or len(originals) > 4 or any(s.status != "ready" for s in originals):
                raise ValueError(
                    "Projektquellen benötigen 1 bis 4 fertig eingelesene Originale; "
                    "eine Teilmenge im Dateidialog auswählen"
                )
            selected = [
                SourceBinding(id=s.id, revision=s.revision, sha256=s.sha256)
                for s in sorted(originals, key=lambda source: source.id)
            ]
            if original and selected != list(original.sources):
                raise ValueError("Quellen einer Folgeversion im Dateidialog ausdrücklich ändern")
            sources = selected
        default_count = (
            len(original.plan.slides) if original and original.plan.kind == "pptx" else 3
        )
        format_goal = goal
        if original and not re.search(
            r"\b(word|docx|powerpoint|pptx|präsentation|presentation|pdf)\b", goal, re.I
        ):
            format_goal += " " + original.plan.kind
        kind, count = request_format(format_goal, default_count)
        if original and original.plan.kind != kind:
            raise ValueError("Folgeversion behält ihr Format; Umwandlung im Dateidialog wählen")
        targets = set(re.findall(r"\b(?:folie|slide)\s+(\d{1,3})\b", goal, re.I)) if base else set()
        if targets and (
            not original
            or original.plan.kind != "pptx"
            or len(targets) != 1
            or not 1 <= int(next(iter(targets))) <= len(original.plan.slides)
            or count != len(original.plan.slides)
        ):
            raise ValueError(
                "Eine vorhandene Folie eindeutig auswählen; sonst Dateidialog verwenden"
            )
        if targets and sources:
            raise ValueError("Einzelne quellengebundene Folien im Dateidialog überarbeiten")
    # The latest user's goal and explicitly requested current project originals
    # are bound. History/memory/retrieval never supply implicit write instructions.
    section_count = (
        1 if re.search(r"\b(?:ein(?:en|em)?|1|one)\s+(?:abschnitt|section)\b", goal, re.I) else None
    )
    body = DraftInput(
        goal=goal,
        kind=kind,  # type: ignore[arg-type]
        slide_count=count,
        section_count=section_count,
        sources=sources,
        base_artifact_id=base.artifact_id if base else None,
        base_revision=base.revision if base else None,
    )
    proposal = await preview(factory, cfg, project_id, body, provider)
    proposed = ArtifactSpec.model_validate(proposal["spec"])
    if targets and original and original.plan.kind == "pptx" and proposed.plan.kind == "pptx":
        target = int(next(iter(targets))) - 1
        if proposed.plan.title != original.plan.title or any(
            slide != original.plan.slides[index]
            for index, slide in enumerate(proposed.plan.slides)
            if index != target
        ):
            raise ValueError("Entwurf verändert weitere Folien; keine neue Version gespeichert")

    def guard(db: Session) -> None:
        current = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        current_chat = db.scalar(
            select(Conversation).where(Conversation.id == chat_id).with_for_update()
        )
        current_message = db.scalar(
            select(Message).where(Message.id == message_id).with_for_update()
        )
        latest = db.scalar(
            select(Message.id)
            .where(
                Message.conversation_id == chat_id, Message.role == "user", Message.active.is_(True)
            )
            .order_by(Message.created.desc(), Message.id.desc())
        )
        if (
            not current
            or current.status != "routing"
            or current.cancel_requested
            or current.conversation_id != chat_id
            or not current_chat
            or current_chat.archived
            or current_chat.memory_scope
            or current_chat.project_id != project_id
            or not current_message
            or not current_message.active
            or latest != message_id
            or current_message.revision != revision
            or digest(current_message.content) != sha
        ):
            raise ValueError("Gespräch oder Dateiwunsch wurde inzwischen geändert oder abgebrochen")

    def linked(db: Session, row: ArtifactRevision) -> None:
        current = db.get(Run, run_id)
        assert current is not None
        snapshot = json.loads(current.context_snapshot or "{}")
        snapshot["artifact"] = {
            "project_id": project_id,
            "artifact_id": row.artifact_id,
            "revision": row.revision,
            "kind": kind,
            "label": "LOCAL_ONLY",
            "message_id": message_id,
            "message_revision": revision,
            "message_sha256": sha,
            "sources": [source.model_dump(mode="json") for source in sources],
            "requires_review": True,
            "base_revision": base.revision if base else None,
        }
        current.context_snapshot = json.dumps(snapshot, ensure_ascii=False)
        current.provider = "local"
        current.model = proposal["provider"]["model"]
        current.provider_revision = proposal["provider"]["revision"]

    save = artifact_service(cfg, factory, guard=guard, on_created=linked)
    return await save(
        project_id,
        base.artifact_id if base else None,
        CreateArtifact(
            request_id=uuid.UUID(run_id),
            spec=proposed,
            expected_revision=base.revision if base else None,
            draft_token=proposal["draft_token"],
        ),
    )
