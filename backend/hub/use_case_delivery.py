"""Explicit, immutable mail previews and single-attempt delivery receipts."""

import json
import re
import time
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, cast
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import Field
from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from hub.db import Base, LoginSession, new_id
from hub.db_locks import ownership_lock
from hub.integrations import Integration
from hub.knowledge_api import Auth
from hub.provider_settings import decrypt
from hub.smtp_client import connect, mailbox, send
from hub.use_cases import Strict, UseCase, UseCaseRun, digest, encode


class MailDefault(Base):
    __tablename__ = "mail_default"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    integration_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revision: Mapped[int] = mapped_column(Integer)


class MailPreview(Base):
    __tablename__ = "use_case_mail_previews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("use_case_runs.id"), index=True)
    snapshot: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)


class MailDelivery(Base):
    __tablename__ = "use_case_mail_deliveries"
    __table_args__ = (UniqueConstraint("preview_id"), UniqueConstraint("request_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    preview_id: Mapped[str] = mapped_column(ForeignKey("use_case_mail_previews.id"))
    request_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20))
    message_id: Mapped[str] = mapped_column(String(160))
    created: Mapped[float] = mapped_column(Float)


class DefaultInput(Strict):
    integration_id: UUID | None = None
    expected_revision: int = Field(ge=0)


class PreviewInput(Strict):
    integration_id: UUID | None = None
    expected_revision: int = Field(ge=1)
    recipient: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=200)


class DeliveryInput(Strict):
    preview_id: UUID
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: UUID


def lock(db: Any) -> None:
    ownership_lock(db)
    if db.bind.dialect.name == "sqlite":
        if not db.connection().connection.driver_connection.in_transaction:
            db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.execute(text("SELECT pg_advisory_xact_lock(791103050)"))


def validate_delivery_integration(db: Any, identifier: str) -> Integration:
    row = db.get(Integration, identifier)
    check = json.loads(row.last_check) if row and row.last_check else {}
    if not row or row.kind != "smtp" or not row.enabled or not row.encrypted_secret:
        raise HTTPException(409, "Aktive Mailverbindung mit Zugangsdaten auswählen")
    if check.get("revision") != row.revision or check.get("status") != "succeeded":
        raise HTTPException(409, "Mailverbindung zuerst unter Integrationen prüfen")
    return cast(Integration, row)


def default_info(db: Any) -> dict[str, Any]:
    row = db.get(MailDefault, 1)
    return {
        "integration_id": row.integration_id if row else None,
        "revision": row.revision if row else 0,
    }


def prompt_mail(db: Any, spec: dict[str, Any]) -> str | None:
    instruction = spec.get("processing_prompt", "") + "\n" + spec.get("text_template", "")
    matches = []
    for row in db.scalars(select(Integration).where(Integration.kind == "smtp")):
        name = re.escape(row.name)
        pattern = (
            r"(?:E-?Mail|Mailversand|Versand)[^\n.!?]{0,60}?(?:über|via)\s+(?:die\s+)?(?:Verbindung\s+)?[\"„]?"
            + name
            + r"[\"“]?(?![\w-])"
        )
        if re.search(pattern, instruction, re.IGNORECASE):
            matches.append(row.id)
    if len(matches) > 1:
        raise HTTPException(409, "Prompt nennt mehrere Mailverbindungen; eine gezielt auswählen")
    return matches[0] if matches else None


def result(
    db: Any, identifier: str, run_id: str, revision: int, *, resolve_mail: bool = True
) -> tuple[str, str | None]:
    case, run = db.get(UseCase, identifier), db.get(UseCaseRun, run_id)
    if not case or not run or run.use_case_id != identifier:
        raise HTTPException(404, "Use-Case-Ergebnis nicht vorhanden")
    if case.revision != revision or run.revision != revision:
        raise HTTPException(409, "Use Case geändert; aktuelles Ergebnis verwenden")
    snapshot = json.loads(run.snapshot)
    if run.execution_run_id:
        from hub.use_case_ai import ai_run_info

        value = ai_run_info(db, run)
        if value["status"] != "succeeded":
            raise HTTPException(409, "Nur fertige Ergebnisse können versendet werden")
        output = value["output"]
    else:
        output = snapshot["output"]
    content = output.get("text", "")
    rows = output.get("rows") or ([output["row"]] if output.get("row") else [])
    if rows:
        content += "\n\n" + " | ".join(output["columns"]) + "\n"
        content += "\n".join(" | ".join(str(v) for v in row) for row in rows)
    if not content.strip() or len(content.encode()) > 200_000:
        raise HTTPException(413, "Ergebnis ist leer oder überschreitet die Mailgrenze")
    choice = snapshot["spec"].get("output_integration_id")
    if resolve_mail and not choice:
        choice = prompt_mail(db, snapshot["spec"])
    return content.strip(), choice


def settle_stalled(db: Any) -> None:
    for row in db.scalars(
        select(MailDelivery).where(
            MailDelivery.status == "sending", MailDelivery.created < time.time() - 300
        )
    ):
        row.status = "uncertain"


def receipt(row: MailDelivery) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status,
        "message_id": row.message_id,
        "created": row.created,
        "message": {
            "sent": "Vom Mailserver angenommen",
            "sending": "Versand läuft; nicht erneut senden",
            "uncertain": "Übernahme unklar. Vor erneutem Versand Postausgang prüfen",
            "failed": "Versand vor Übergabe fehlgeschlagen",
        }.get(row.status, row.status),
    }


def cleanup_deliveries(db: Any, identifier: str) -> None:
    settle_stalled(db)
    previews = list(
        db.scalars(
            select(MailPreview).where(
                MailPreview.run_id.in_(
                    select(UseCaseRun.id).where(UseCaseRun.use_case_id == identifier)
                )
            )
        )
    )
    ids = [p.id for p in previews]
    if db.scalar(
        select(MailDelivery.id).where(
            MailDelivery.preview_id.in_(ids), MailDelivery.status == "sending"
        )
    ):
        raise HTTPException(409, "Mailversand läuft; nach Abschluss löschen")
    db.execute(delete(MailDelivery).where(MailDelivery.preview_id.in_(ids)))
    db.execute(delete(MailPreview).where(MailPreview.id.in_(ids)))


def install(app: FastAPI, cfg: Any, factory: Any) -> None:
    @app.get("/api/integrations/mail-default")
    def get_default(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return default_info(db)

    @app.put("/api/integrations/mail-default")
    def set_default(body: DefaultInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            if default_info(db)["revision"] != body.expected_revision:
                raise HTTPException(409, "Primäre Mailverbindung geändert; neu laden")
            if body.integration_id:
                validate_delivery_integration(db, str(body.integration_id))
            row = db.get(MailDefault, 1)
            if not row:
                row = MailDefault(id=1, revision=0)
                db.add(row)
            row.integration_id = str(body.integration_id) if body.integration_id else None
            row.revision += 1
            db.commit()
            return default_info(db)

    prefix = "/api/use-cases/{identifier}/runs/{run_id}"

    @app.post(prefix + "/delivery-preview")
    def preview(identifier: UUID, run_id: UUID, body: PreviewInput, auth: Auth) -> dict[str, Any]:
        try:
            mailbox(body.recipient)
            if any(ord(c) < 32 for c in body.subject) or not body.subject.strip():
                raise ValueError("Invalid subject")
        except ValueError:
            raise HTTPException(422, "Empfänger oder Betreff prüfen") from None
        with factory() as db:
            lock(db)
            content, configured = result(
                db,
                str(identifier),
                str(run_id),
                body.expected_revision,
                resolve_mail=not bool(body.integration_id),
            )
            default = default_info(db)
            choice = (
                str(body.integration_id)
                if body.integration_id
                else configured or default["integration_id"]
            )
            if not choice:
                raise HTTPException(
                    409, "Primäre Mailverbindung festlegen oder Verbindung auswählen"
                )
            integration = validate_delivery_integration(db, choice)
            snapshot = {
                "case_id": str(identifier),
                "revision": body.expected_revision,
                "integration_id": choice,
                "integration_revision": integration.revision,
                "default_revision": default["revision"]
                if not body.integration_id and not configured
                else None,
                "sender": json.loads(integration.config)["sender"],
                "recipient": body.recipient,
                "subject": body.subject.strip(),
                "text": content,
                "result_digest": digest(content),
            }
            encoded = encode(snapshot)
            row = MailPreview(
                run_id=str(run_id),
                snapshot=encoded,
                sha256=digest(encoded),
                expires=time.time() + 900,
            )
            db.add(row)
            db.flush()
            response = {
                "preview_id": row.id,
                "digest": row.sha256,
                "expires": row.expires,
                "integration_name": integration.name,
                "label": "LOCAL_ONLY",
                **snapshot,
            }
            db.commit()
            return response

    @app.get(prefix + "/deliveries")
    def deliveries(identifier: UUID, run_id: UUID, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            lock(db)
            settle_stalled(db)
            db.commit()
            item = db.get(UseCaseRun, str(run_id))
            if not item or item.use_case_id != str(identifier):
                raise HTTPException(404, "Ergebnis nicht gefunden")
            return [
                receipt(d)
                for d in db.scalars(
                    select(MailDelivery)
                    .order_by(MailDelivery.created.desc())
                    .where(
                        MailDelivery.preview_id.in_(
                            select(MailPreview.id).where(MailPreview.run_id == str(run_id))
                        )
                    )
                )
            ]

    @app.post(prefix + "/deliveries")
    def deliver(identifier: UUID, run_id: UUID, body: DeliveryInput, auth: Auth) -> dict[str, Any]:
        def validate(db: Any, preview: MailPreview) -> tuple[dict[str, Any], Integration]:
            snapshot = json.loads(preview.snapshot)
            if (
                preview.run_id != str(run_id)
                or snapshot["case_id"] != str(identifier)
                or preview.sha256 != body.digest
            ):
                raise HTTPException(409, "Mailvorschau passt nicht zum Ergebnis")
            if preview.expires < time.time():
                raise HTTPException(409, "Mailvorschau abgelaufen; neu prüfen")
            content, _ = result(
                db, str(identifier), str(run_id), snapshot["revision"], resolve_mail=False
            )
            integration = validate_delivery_integration(db, snapshot["integration_id"])
            if (
                integration.revision != snapshot["integration_revision"]
                or digest(content) != snapshot["result_digest"]
            ):
                raise HTTPException(
                    409, "Mailverbindung oder Ergebnis geändert; Vorschau neu öffnen"
                )
            if (
                snapshot["default_revision"] is not None
                and default_info(db)["revision"] != snapshot["default_revision"]
            ):
                raise HTTPException(409, "Primäre Mailverbindung geändert; Vorschau neu öffnen")
            return snapshot, integration

        with factory() as db:
            lock(db)
            settle_stalled(db)
            previous = db.scalar(
                select(MailDelivery).where(MailDelivery.request_id == str(body.request_id))
            )
            if previous:
                if previous.preview_id != str(body.preview_id):
                    raise HTTPException(409, "Versandanfrage bereits anderweitig verwendet")
                preview_row = db.get(MailPreview, previous.preview_id)
                if (
                    not preview_row
                    or preview_row.sha256 != body.digest
                    or preview_row.run_id != str(run_id)
                    or json.loads(preview_row.snapshot)["case_id"] != str(identifier)
                ):
                    raise HTTPException(409, "Versandanfrage passt nicht zur Vorschau")
                response = receipt(previous)
                db.commit()
                return response
            preview_row = db.get(MailPreview, str(body.preview_id))
            if not preview_row:
                raise HTTPException(404, "Mailvorschau nicht gefunden")
            if db.scalar(select(MailDelivery.id).where(MailDelivery.preview_id == preview_row.id)):
                raise HTTPException(
                    409, "Diese Vorschau wurde bereits verwendet; Versandstatus prüfen"
                )
            snapshot, integration = validate(db, preview_row)
            config = json.loads(integration.config)
            assert integration.encrypted_secret
            password = decrypt(cfg, "integration:" + integration.id, integration.encrypted_secret)
            row = MailDelivery(
                preview_id=preview_row.id,
                request_id=str(body.request_id),
                status="sending",
                message_id=make_msgid(domain="obdaai.local"),
                created=time.time(),
            )
            db.add(row)
            db.flush()
            delivery_id = row.id
            db.commit()

        handed_off = False

        def boundary() -> None:
            nonlocal handed_off
            with factory() as db:
                lock(db)
                if auth is not None:
                    session = db.get(LoginSession, auth.token_hash)
                    if session is None or session.expires <= time.time():
                        raise HTTPException(401, "Sitzung vor Versand beendet")
                current = db.get(MailPreview, str(body.preview_id))
                if not current:
                    raise HTTPException(409, "Mailvorschau entfernt")
                validate(db, current)
            handed_off = True

        try:
            message = EmailMessage()
            message["From"], message["To"], message["Subject"] = (
                snapshot["sender"],
                snapshot["recipient"],
                snapshot["subject"],
            )
            message["Message-ID"] = row.message_id
            message.set_content(snapshot["text"])
            connection = connect(cfg, config, password)
            try:
                send(connection, message, boundary)
                status = "sent"
            finally:
                connection.close()
        except Exception:
            status = "uncertain" if handed_off else "failed"
        with factory() as db:
            lock(db)
            saved = db.get(MailDelivery, delivery_id)
            saved.status = status
            db.commit()
            return receipt(saved)
