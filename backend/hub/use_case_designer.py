"""A durable model conversation that proposes, but never saves or executes, a workflow."""

import time
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import Field, ValidationError
from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint, delete, func, select
from sqlalchemy.orm import Mapped, mapped_column

from hub.db import Base, Conversation, Message, Run, new_id
from hub.db_locks import ownership_lock
from hub.knowledge_api import Auth
from hub.policy import ContextPart, Privacy
from hub.routing_settings import read_options
from hub.use_case_ai import ACTIVE, execution_text, model_json, start_development
from hub.use_cases import Definition, Strict, digest, encode


class UseCaseDesigner(Base):
    __tablename__ = "use_case_designers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), unique=True)
    model_mode: Mapped[str] = mapped_column(String(20))
    created: Mapped[float] = mapped_column(Float)


class UseCaseDesignerTurn(Base):
    __tablename__ = "use_case_designer_turns"
    __table_args__ = (UniqueConstraint("designer_id", "request_id"),)
    designer_id: Mapped[str] = mapped_column(ForeignKey("use_case_designers.id"), primary_key=True)
    turn: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    execution_run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)


class StartInput(Strict):
    prompt: str = Field(min_length=1, max_length=12000)
    request_id: UUID
    model_mode: Literal["local", "auto", "cloud"] = "local"


class MessageInput(Strict):
    content: str = Field(min_length=1, max_length=12000)
    request_id: UUID
    expected_turn: int = Field(ge=1)


def proposal_output(text: str) -> tuple[str, dict[str, Any] | None]:
    value = model_json(text)
    if not isinstance(value, dict) or set(value) != {"message", "proposal"}:
        raise ValueError("KI-Vorschlag benötigt message und proposal im JSON-Format")
    message = value["message"]
    if not isinstance(message, str) or not message.strip() or len(message) > 12000:
        raise ValueError("KI-Dialogtext fehlt oder überschreitet das Limit")
    if value["proposal"] is None:
        return message, None
    proposed = value["proposal"]
    if not isinstance(proposed, dict):
        raise ValueError("KI-Vorschlag benötigt eine gültige Use-Case-Definition")
    # Connections are selected by the human in the builder, never by model-generated IDs.
    proposed = dict(proposed)
    proposed.pop("integrations", None)
    proposed["integration_inputs"] = []
    proposed["integration_processing"] = []
    proposed["output_integration_id"] = None
    spec = Definition.model_validate(proposed)
    if spec.execution_kind != "ai":
        raise ValueError("KI-Vorschlag benötigt einen Verarbeitungsprompt")
    return message, spec.model_dump()


def instruction() -> str:
    return (
        "Du hilfst im Erstellungsdialog einen wiederverwendbaren KI Use Case zu entwerfen. "
        "Erfrage gezielt Ziel, erforderliche Eingaben, Verarbeitungsprompt/Kontext und "
        "gewünschte Ausgabe. Stelle höchstens zwei kurze Rückfragen pro Antwort. Wenn "
        "genug Angaben vorliegen, erstelle einen vollständigen bearbeitbaren Vorschlag. "
        "Änderungswünsche beziehen sich auf den bisherigen Entwurf. Führe den Use Case "
        "nicht aus, speichere nichts, sende keine Mail und nutze keine Werkzeuge. "
        "Externe Integrationen werden anschließend vom Menschen ausgewählt; erfinde "
        "keine Verbindungen, IDs oder Zugangsdaten. Verwende execution_kind=ai und "
        "einen konkreten processing_prompt. Antworte ausschließlich als JSON mit genau "
        'diesen Schlüsseln: {"message":"Dialogtext oder Rückfrage", "proposal":null}. '
        "Sobald ein Entwurf vorliegt, ersetze null durch eine Definition dieses Schemas: "
        + encode(Definition.model_json_schema())
    )


def enqueue(db: Any, cfg: Any, item: UseCaseDesigner, content: str) -> Run:
    conversation = db.get(Conversation, item.conversation_id)
    if conversation is None:
        raise HTTPException(404, "Erstellungsdialog nicht gefunden")
    label = Privacy.CLOUD_ALLOWED if conversation.cloud_allowed else Privacy.LOCAL_ONLY
    question = Message(conversation_id=conversation.id, role="user", content=content, label=label)
    db.add(question)
    db.flush()
    parts = [
        ContextPart(content=instruction(), source_id="use-case-designer", revision=1, label=label)
    ]
    roles = ["system"]
    for message in db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created, Message.id)
    ):
        parts.append(
            ContextPart(
                content=message.content,
                source_id=message.id,
                revision=message.revision,
                label=Privacy(message.label),
            )
        )
        roles.append(message.role)
    if sum(len(p.content) for p in parts) > cfg.context_limit:
        raise HTTPException(
            413, "Erstellungsdialog zu groß. Neuen Entwurf mit kürzerem Kontext starten."
        )
    snapshot = {
        "use_case_designer": {"id": item.id},
        "parts": [p.model_dump(mode="json") for p in parts],
        "roles": roles,
        "sources": [],
        "model_local_only": item.model_mode == "local",
        "model_cloud_only": item.model_mode == "cloud",
        "web_search_allowed": False,
        "routing_options": read_options(db),
    }
    execution = Run(
        conversation_id=conversation.id, status="queued", context_snapshot=encode(snapshot)
    )
    db.add(execution)
    db.flush()
    if not cfg.database_url.startswith("sqlite"):
        from hub.jobs import enqueue as enqueue_job

        enqueue_job(db, cfg, execution.id)
    return execution


def info(db: Any, item: UseCaseDesigner) -> dict[str, Any]:
    turns = list(
        db.scalars(
            select(UseCaseDesignerTurn)
            .where(UseCaseDesignerTurn.designer_id == item.id)
            .order_by(UseCaseDesignerTurn.turn)
        )
    )
    latest = turns[-1]
    execution = db.get(Run, latest.execution_run_id)
    messages: list[dict[str, str]] = []
    for message in db.scalars(
        select(Message)
        .where(Message.conversation_id == item.conversation_id)
        .order_by(Message.created, Message.id)
    ):
        content = message.content
        if message.role == "assistant":
            try:
                content, _ = proposal_output(content)
            except (ValueError, ValidationError):
                pass
        messages.append({"role": message.role, "content": content})
    text = execution_text(db, execution)
    proposal = None
    validation_error = None
    if execution.status == "succeeded":
        try:
            _, proposal = proposal_output(text)
        except (ValueError, ValidationError):
            validation_error = (
                "KI-Ausgabe ist kein gültiger Entwurf. Bitte konkretisieren oder erneut "
                "anfragen; Rohtext bleibt erhalten."
            )
    return {
        "id": item.id,
        "turn": latest.turn,
        "status": execution.status,
        "execution_run_id": execution.id,
        "model_mode": item.model_mode,
        "messages": messages,
        "proposal": proposal,
        "validation_error": validation_error,
        "error": execution.error,
        "provider": execution.provider,
        "model": execution.model,
    }


def install(app: FastAPI, cfg: Any, factory: Any) -> None:
    prefix = "/api/use-case-designer/dialogues"

    def get(db: Any, identifier: str) -> UseCaseDesigner:
        item = db.get(UseCaseDesigner, identifier)
        if item is None:
            raise HTTPException(404, "Erstellungsdialog nicht gefunden")
        return cast(UseCaseDesigner, item)

    @app.post(prefix)
    async def start(body: StartInput, auth: Auth) -> dict[str, Any]:
        if not body.prompt.strip():
            raise HTTPException(422, "Bitte die gewünschte Anwendung beschreiben")
        with factory() as db:
            ownership_lock(db)
            request_digest = digest(encode(body.model_dump(mode="json")))
            existing = db.scalar(
                select(UseCaseDesigner).where(UseCaseDesigner.request_id == str(body.request_id))
            )
            if existing:
                if existing.request_digest != request_digest:
                    raise HTTPException(409, "Anfragekennung gehört zu anderem Erstellungsdialog")
                return info(db, existing)
            if body.model_mode == "cloud" and not cfg.cloud_enabled:
                raise HTTPException(409, "Cloud ist serverseitig noch nicht freigegeben")
            if db.scalar(select(func.count()).select_from(UseCaseDesigner)) >= 1000:
                raise HTTPException(413, "Maximal 1000 Erstellungsdialoge; alte Entwürfe löschen")
            conversation = Conversation(
                purpose="use_case_designer",
                title="Use Case entwerfen",
                manual_title=True,
                cloud_allowed=body.model_mode != "local" and cfg.cloud_enabled,
            )
            db.add(conversation)
            db.flush()
            item = UseCaseDesigner(
                request_id=str(body.request_id),
                request_digest=request_digest,
                conversation_id=conversation.id,
                model_mode=body.model_mode,
                created=time.time(),
            )
            db.add(item)
            db.flush()
            execution = enqueue(db, cfg, item, body.prompt)
            db.add(
                UseCaseDesignerTurn(
                    designer_id=item.id,
                    turn=1,
                    request_id=str(body.request_id),
                    request_digest=request_digest,
                    execution_run_id=execution.id,
                )
            )
            db.flush()
            result = info(db, item)
            db.commit()
            start_development(app, cfg, factory, execution.id)
            return result

    @app.get(prefix + "/{identifier}")
    def detail(identifier: str, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return info(db, get(db, identifier))

    @app.post(prefix + "/{identifier}/messages")
    async def message(identifier: str, body: MessageInput, auth: Auth) -> dict[str, Any]:
        if not body.content.strip():
            raise HTTPException(422, "Bitte eine Antwort oder Änderung eingeben")
        with factory() as db:
            ownership_lock(db)
            item = get(db, identifier)
            request_digest = digest(encode(body.model_dump(mode="json")))
            replay = db.scalar(
                select(UseCaseDesignerTurn).where(
                    UseCaseDesignerTurn.designer_id == identifier,
                    UseCaseDesignerTurn.request_id == str(body.request_id),
                )
            )
            if replay:
                if replay.request_digest != request_digest:
                    raise HTTPException(409, "Anfragekennung gehört zu anderer Antwort")
                return info(db, item)
            current = info(db, item)
            if current["turn"] != body.expected_turn or current["status"] in ACTIVE:
                raise HTTPException(409, "Dialog geändert oder Antwort läuft noch")
            if current["turn"] >= 40:
                raise HTTPException(413, "Erstellungsdialog mit maximal 40 Nachrichten")
            execution = enqueue(db, cfg, item, body.content)
            db.add(
                UseCaseDesignerTurn(
                    designer_id=item.id,
                    turn=current["turn"] + 1,
                    request_id=str(body.request_id),
                    request_digest=request_digest,
                    execution_run_id=execution.id,
                )
            )
            db.flush()
            result = info(db, item)
            db.commit()
            start_development(app, cfg, factory, execution.id)
            return result

    @app.post(prefix + "/{identifier}/cancel")
    def cancel(identifier: str, auth: Auth) -> dict[str, bool]:
        with factory() as db:
            ownership_lock(db)
            execution = db.get(Run, info(db, get(db, identifier))["execution_run_id"])
            if execution and execution.status in ACTIVE:
                execution.cancel_requested = True
            db.commit()
        return {"cancel_requested": True}

    @app.delete(prefix + "/{identifier}")
    def remove(identifier: str, auth: Auth) -> dict[str, bool]:
        from hub.deletion import permanently_delete

        with factory() as db:
            ownership_lock(db)
            item = get(db, identifier)
            if info(db, item)["status"] in ACTIVE:
                raise HTTPException(409, "Lauf zuerst abbrechen und Abschluss abwarten")
            conversation_id = item.conversation_id
            db.execute(
                delete(UseCaseDesignerTurn).where(UseCaseDesignerTurn.designer_id == identifier)
            )
            db.delete(item)
            db.flush()
            permanently_delete(
                db, cfg, "conversation", conversation_id, None, allow_use_case=True, commit=False
            )
            db.commit()
        return {"ok": True}
