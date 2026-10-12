"""Explicit project-chat file requests use the same bounded artifact service."""

import json
import re
import unicodedata
import uuid
from pathlib import PurePath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hub.artifact_api import CreateArtifact, artifact_service
from hub.artifact_chat import ChatSource
from hub.artifact_drafts import DraftInput, preview
from hub.artifact_specs import ArtifactSpec, SourceBinding
from hub.artifacts import digest, spec_for
from hub.db import Artifact, ArtifactRevision, Conversation, Message, Run, Source


def artifact_clarification(goal: str) -> str | None:
    """Ask for content when the request contains only format and layout details."""
    try:
        kind, count = request_format(goal)
    except ValueError:
        return None
    remainder = re.sub(
        r"\b(?:bitte|please|erstelle|erzeuge|generiere|schreibe|mach|mache|create|generate|make|"
        r"eine[nmrs]?|ein[nmrs]?|a|an|the|mir|me|für|for|mich|uns|us|mit|with|und|and|"
        r"word|docx|powerpoint|pptx|präsentation|presentation|pdf|datei|file|dokument|document|"
        r"folien?|slides?|seiten?|pages?|abschnitte?|sections?|editable|editierbar[e]?|"
        r"eins|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|one|two|three|four|five|six|seven|eight|nine|ten)\b|\d+",
        " ",
        goal,
        flags=re.I,
    )
    if re.search(r"\w", remainder):
        return None
    if kind == "pptx":
        return (
            f"Zu welchem Thema soll ich die PowerPoint-Präsentation mit {count} Folien erstellen? "
            "Du kannst auch Zielgruppe, wichtige Inhalte und den gewünschten Stil nennen."
        )
    name = "Word-Dokument" if kind == "docx" else "PDF-Dokument"
    return (
        f"Welches Thema oder welchen Inhalt soll das {name} haben? "
        "Du kannst auch Zielgruppe und den gewünschten Stil nennen."
    )


def clarification_receipt(message: Message, question: str) -> dict[str, Any]:
    return {
        "message_id": message.id,
        "message_revision": message.revision,
        "message_sha256": digest(message.content),
        "goal": message.content,
        "question_sha256": digest(question),
    }


def resolved_chat_goal(db: Session, chat: Conversation, message: Message) -> str:
    """Resolve only a server-owned, still-active, immediate clarification turn."""
    active = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == chat.id, Message.active.is_(True))
            .order_by(Message.created, Message.id)
        )
    )
    position = next((i for i, row in enumerate(active) if row.id == message.id), -1)
    if position < 2 or active[position - 1].role != "assistant":
        return message.content
    reply = active[position - 1]
    prior = db.get(Run, reply.run_id) if reply.run_id else None
    if not prior or prior.status != "succeeded" or prior.conversation_id != chat.id:
        return message.content
    receipt = json.loads(prior.context_snapshot or "{}").get("artifact_clarification")
    if not isinstance(receipt, dict):
        return message.content
    origin = active[position - 2]
    if (
        origin.role != "user"
        or origin.id != receipt.get("message_id")
        or origin.revision != receipt.get("message_revision")
        or digest(origin.content) != receipt.get("message_sha256")
        or origin.content != receipt.get("goal")
        or digest(reply.content) != receipt.get("question_sha256")
        or artifact_clarification(origin.content) != reply.content
    ):
        return message.content
    # A new explicit file command replaces the pending request; do not combine
    # incompatible formats or silently override a fresh instruction.
    try:
        request_format(message.content)
    except ValueError:
        pass
    else:
        return message.content
    if re.match(r"^\s*(?:abbrechen|vergiss|cancel|never mind|stopp|stop)\b", message.content, re.I):
        return message.content
    return origin.content + "\nThema und Inhalt: " + message.content


def requests_revision(goal: str) -> bool:
    return bool(
        re.search(
            r"\b(überarbeite|ändere|kürze|drehe|schneide|verkleinere|vergrößere|skaliere|revise|shorten|update|rotate|crop|resize)\b",
            goal,
            re.I,
        )
    )


def named_originals(db: Session, project_id: str, goal: str) -> list[Source]:
    text = unicodedata.normalize("NFC", goal).casefold()
    selected: list[tuple[int, Source]] = []
    names: set[str] = set()
    for source in db.scalars(select(Source).where(Source.project_id == project_id)):
        name = unicodedata.normalize("NFC", source.name).casefold()
        match = re.search(r"(?<![\w./\\-])" + re.escape(name) + r"(?![\w-]|\.[\w])", text)
        if match:
            if name in names or source.status != "ready":
                raise ValueError("Quelldatei ist mehrdeutig oder noch nicht fertig eingelesen")
            names.add(name)
            selected.append((match.start(), source))
    if len(selected) > 20:
        raise ValueError("Höchstens zwanzig ausdrücklich benannte Originale auswählen")
    return [source for _, source in sorted(selected, key=lambda item: item[0])]


def media_operation(goal: str, originals: list[Source]) -> str | None:
    if not originals or not re.search(
        r"^\s*(?:(?:bitte|please)\s+)?(?:erstelle|erzeuge|generiere|kombiniere|"
        r"führe|füge|verbinde|extrahiere|entferne|drehe|schneide|verkleinere|vergrößere|skaliere|ändere|"
        r"teile|trenne|create|make|merge|split|rotate|crop|resize)\b",
        goal,
        re.I,
    ):
        return None
    suffixes = {PurePath(s.name).suffix.lower() for s in originals}
    if suffixes == {".pdf"} and re.search(
        r"\b(seiten?|pages?|zusammenführen|zusammen|kombiniere|merge|extrahiere|teile|trenne|split|drehe|rotate)\b",
        goal,
        re.I,
    ):
        return "pdf"
    if suffixes.issubset({".png", ".jpg", ".jpeg", ".webp"}) and re.search(
        r"\b(collage|schneide|zuschnitt|crop|verkleinere|vergrößere|resize|skaliere)\b", goal, re.I
    ):
        return "image"
    return None


def ambiguous_file_revision(goal: str) -> bool:
    """Reject direct file edits with no bound target before model classification."""
    return bool(
        re.search(
            r"^\s*(?:(?:bitte|please)\s+)?(?:überarbeite|ändere|kürze|drehe|schneide|verkleinere|vergrößere|skaliere|revise|shorten|update|rotate|crop|resize)\s+",
            goal,
            re.I,
        )
        and re.search(
            r"\b(?:word(?:[- ]?(?:datei|dokument|file|document))?|powerpoint|"
            r"präsentation|datei|dokument|docx|pptx|pdf|bild|image|png|jpeg|jpg|file|presentation|document)\b",
            goal,
            re.I,
        )
        and not explicit_revision_target(goal)
    )


def explicit_revision_target(goal: str) -> bool:
    name = (
        r"(?:word[- ](?:datei|dokument|file|document)|worddatei|worddokument|"
        r"powerpoint(?:[- ](?:datei|file))?|präsentation|datei|version|dokument|"
        r"docx|pptx|pdf|bild|image|png|jpeg|jpg|file|presentation|document)"
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
    action = (
        r"^\s*(?:(?:bitte|please)\s+)?(?:überarbeite|ändere|kürze|drehe|schneide|"
        r"verkleinere|vergrößere|skaliere|revise|shorten|update|rotate|crop|resize)\s+"
    )
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


def chat_base(db: Session, chat_id: str, project_id: str | None, run: Run) -> ArtifactRevision:
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
            or (project_id is None and artifact.conversation_id != chat_id)
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


def requests_public_research(goal: str) -> bool:
    """A clear direct user's public-search command is a mandatory step, not a grant."""
    direct = re.search(
        r"^\s*(?:(?:bitte|please)\s+)?(?:recherchiere|suche|research|search)\b", goal, re.I
    )
    public = re.search(r"\b(?:öffentlich|public|online|internet|web)\b|https://", goal, re.I)
    negative = re.search(
        r"\b(?:ohne|nicht|without|no)\b.{0,25}\b(?:web|internet|online)\b", goal, re.I
    )
    if direct and public and negative:
        raise ValueError("Öffentliche Recherche und Webverbot widersprechen sich")
    return bool(direct and public)


def requests_answer_source(goal: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:(?:bitte|please)\s+)?(?:erstelle|erzeuge|generiere|schreibe|mach|mache|create|make|write)\b.{0,120}\b(?:daraus|aus\s+(?:der\s+)?letzten\s+antwort|from\s+(?:your\s+)?last\s+(?:answer|response))\b",
            goal,
            re.I,
        )
    )


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
        r"\b(erstelle|erzeuge|generiere|schreibe|mach|mache|create|generate|make)\b", goal, re.I
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
    factory: Any, cfg: Any, run_id: str, provider: Any = None, *, research_id: str | None = None
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
        if not chat or chat.purpose != "chat" or chat.memory_scope or chat.archived or not message:
            raise ValueError("Dateien im aktiven Gespräch erstellen")
        project_id, chat_id, message_id = chat.project_id, chat.id, message.id
        goal = resolved_chat_goal(db, chat, message)
        answer_source = None
        if requests_answer_source(goal) and not requests_revision(goal):
            active = list(
                db.scalars(
                    select(Message)
                    .where(Message.conversation_id == chat.id, Message.active.is_(True))
                    .order_by(Message.created, Message.id)
                )
            )
            position = next(i for i, item in enumerate(active) if item.id == message.id)
            answer = next(
                (item for item in reversed(active[:position]) if item.role == "assistant"), None
            )
            if answer is None:
                raise ValueError("Keine vorherige Chatantwort für diesen Dateiwunsch vorhanden")
            answer_source = ChatSource(
                conversation_id=chat.id, message_id=answer.id, revision=answer.revision
            )

        revision, sha = message.revision, digest(message.content)
        if len(goal) > 4000:
            raise ValueError("Dateiwunsch darf höchstens 4000 Zeichen enthalten")
        named = named_originals(db, project_id, goal) if project_id else []
        operation = media_operation(goal, named)
        revising = requests_revision(goal) and not operation
        if revising and not explicit_revision_target(goal):
            raise ValueError(
                "Die letzte Chat-Datei ausdrücklich benennen oder eine konkrete Version "
                "im Dateidialog wählen; es wurde keine Datei geändert"
            )
        base = chat_base(db, chat_id, project_id, run) if revising else None
        original = spec_for(base) if base else None
        sources = list(original.sources) if original else []
        if original and (
            original.plan.kind == "image" or (original.plan.kind == "pdf" and original.plan.pages)
        ):
            operation = original.plan.kind
        if named and not original:
            sources = [SourceBinding(id=s.id, revision=s.revision, sha256=s.sha256) for s in named]
        elif requests_project_sources(goal):
            if project_id is None:
                raise ValueError("Projektquellen benötigen ein Gespräch in diesem Projekt")
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
        # A literal original name is a source selection, not an output format.
        for source in named:
            format_goal = re.sub(re.escape(source.name), "Quelldatei", format_goal, flags=re.I)
        kind, count = (
            (operation, default_count) if operation else request_format(format_goal, default_count)
        )
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
    # The latest user's goal and explicitly requested current project originals
    # are bound. History/memory/retrieval never supply implicit write instructions.
    section_count = (
        1 if re.search(r"\b(?:ein(?:en|em)?|1|one)\s+(?:abschnitt|section)\b", goal, re.I) else None
    )
    body = DraftInput(
        goal=goal,
        kind=kind,  # type: ignore[arg-type]
        pdf_mode="pages" if operation == "pdf" else "content",
        slide_count=count,
        section_count=section_count,
        target_slide=int(next(iter(targets))) if targets else None,
        chat_source=answer_source,
        sources=sources,
        base_artifact_id=base.artifact_id if base else None,
        base_revision=base.revision if base else None,
    )
    proposal = await preview(
        factory,
        cfg,
        project_id,
        body,
        provider,
        research_id=research_id,
        conversation_id=chat_id if project_id is None else None,
    )
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
            or resolved_chat_goal(db, current_chat, current_message) != goal
        ):
            raise ValueError("Gespräch oder Dateiwunsch wurde inzwischen geändert oder abgebrochen")

    def linked(db: Session, row: ArtifactRevision) -> None:
        current = db.get(Run, run_id)
        assert current is not None
        snapshot = json.loads(current.context_snapshot or "{}")
        snapshot["artifact"] = {
            "project_id": project_id,
            "conversation_id": chat_id if project_id is None else None,
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
            chat_source=answer_source,
        ),
        conversation_id=chat_id if project_id is None else None,
    )
