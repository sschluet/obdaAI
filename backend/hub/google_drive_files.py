"""Human-scoped Drive knowledge snapshots and explicit, durable artifact exports.

Google content remains LOCAL_ONLY data. Only new files in the application's own
folder can be written. An uncertain POST is reconciled by identity, never repeated.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from collections.abc import Generator
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import Field
from sqlalchemy import Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from hub.action_api import StrictInput, digest, encode
from hub.artifact_scope import owner
from hub.artifacts import bind_sources, checked_manifest, output_file, spec_for
from hub.config import Settings
from hub.db import Artifact, ArtifactRevision, Base, KnowledgeConnection, Project, Source, new_id
from hub.db_locks import ownership_lock
from hub.extract import EXTENSIONS, MAX_BYTES
from hub.integrations import Integration
from hub.knowledge_api import Auth
from hub.knowledge_clients import ConnectionInput, Document

_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
FOLDER_MIME = "application/vnd.google-apps.folder"


class GoogleDriveTransfer(Base):
    __tablename__ = "google_drive_transfers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    integration_id: Mapped[str] = mapped_column(String(36), index=True)
    profile_revision: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="preparing")
    remote_id: Mapped[str] = mapped_column(String(256), default="")
    folder_id: Mapped[str] = mapped_column(String(256), default="")
    artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    artifact_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), default="")
    content_md5: Mapped[str] = mapped_column(String(32), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(240), default="")
    mime_type: Mapped[str] = mapped_column(String(160), default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    updated: Mapped[float] = mapped_column(Float, default=time.time)
    error: Mapped[str] = mapped_column(String(80), default="")


class DriveSourceInput(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)
    folder_id: str = Field(default="root", pattern=r"^[A-Za-z0-9_-]{1,256}$")
    max_files: int = Field(default=50, ge=1, le=1000, strict=True)


class DriveFolderInput(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)
    request_id: UUID


class DriveReconcileInput(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)


class DriveExportInput(DriveFolderInput):
    artifact_id: UUID
    artifact_revision: int = Field(ge=1, strict=True)
    cloud_upload_approved: bool = Field(default=False, strict=True)


def _source_profile(db: Session, body: ConnectionInput) -> Integration:
    row = db.get(Integration, str(body.integration_id), populate_existing=True)
    try:
        config = json.loads(row.config) if row else {}
        if not (
            row
            and row.kind == "google_drive"
            and row.enabled
            and row.encrypted_secret
            and row.revision == body.integration_revision
            and config.get("connected") is True
            and config.get("enable_source") is True
            and (
                (config.get("source_folder_id") or "root") == "root"
                or (config.get("source_folder_id") or "root") == (body.folder or "root")
            )
            and config.get("account_email")
        ):
            raise ValueError("Drive source permission changed")
        return row
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Google-Drive-Quelle benötigt eine aktuelle Freigabe") from None


def source_enabled(db: Session, connection: KnowledgeConnection) -> bool:
    if connection.kind != "google_drive":
        return True
    try:
        _source_profile(db, ConnectionInput.model_validate_json(connection.config))
        return True
    except ValueError:
        return False


def rebind_source_revision(
    db: Session, integration_id: str, old_revision: int, new_revision: int
) -> None:
    """Carry source authority only across caller-proven source-neutral controls.

    Callers may use this only for enable/disable or verified storage-folder creation,
    never for OAuth/account, scopes, credentials, or source-folder edits.
    """
    profile = db.get(Integration, integration_id, populate_existing=True)
    if not profile or profile.kind != "google_drive" or profile.revision != new_revision:
        raise ValueError("Drive revision changed")
    config = json.loads(profile.config)
    for connection in db.scalars(
        select(KnowledgeConnection).where(
            KnowledgeConnection.kind == "google_drive",
            KnowledgeConnection.target_ref == integration_id,
        )
    ):
        body = ConnectionInput.model_validate_json(connection.config)
        if (
            str(body.integration_id) != integration_id
            or body.integration_revision != old_revision
            or (
                (config.get("source_folder_id") or "root") != "root"
                and (body.folder or "root") != (config.get("source_folder_id") or "root")
            )
            or not config.get("account_email")
            or config.get("connected") is not True
            or config.get("enable_source") is not True
        ):
            continue
        body.integration_revision = new_revision
        connection.config = encode(body.public())
        connection.revision += 1
        if connection.status == "indexing":
            previous = db.scalar(
                select(Source.id)
                .where(Source.project_id == connection.project_id, Source.status == "ready")
                .limit(1)
            )
            connection.status = "ready" if previous else "needs_setup"
            connection.error = ""


def validate_source(db: Session, body: ConnectionInput) -> None:
    if body.kind == "google_drive":
        _source_profile(db, body)


def drive_documents(
    factory: sessionmaker[Session], cfg: Settings, body: ConnectionInput, *, probe: bool = False
) -> Generator[Document, None, None]:
    from hub.google_drive_client import EXPORTS, DriveClient
    from hub.google_drive_setup import access_token, authority_guard

    integration_identifier = str(body.integration_id)
    revision = body.integration_revision
    assert revision is not None

    def guard() -> None:
        authority_guard(factory, cfg, integration_identifier, revision, "source")()
        with factory() as db:
            validate_source(db, body)

    guard()
    token = access_token(
        factory, cfg, integration_identifier, revision, capability="source", before_send=guard
    )
    count, pages, page = 0, 0, ""
    with DriveClient(token, before_send=guard) as client:
        while pages < 20:
            response = client.list_files(parent=body.folder or "root", page_token=page, limit=50)
            pages += 1
            if probe:
                return
            for metadata in response["files"]:
                file_id = metadata["id"]
                mime = metadata["mimeType"]
                if mime == FOLDER_MIME or mime == "application/vnd.google-apps.shortcut":
                    continue
                name = PurePosixPath(metadata["name"]).name
                # Native Docs/Sheets/Slides are exported locally into supported formats.
                if mime in EXPORTS:
                    extension = EXPORTS[mime][1]
                    if not name.lower().endswith(extension):
                        name += extension
                elif PurePosixPath(name).suffix.lower() not in EXTENSIONS:
                    continue
                if (
                    not name
                    or name.startswith(".")
                    or len(name) > 220
                    or "\\" in name
                    or any(ord(c) < 32 for c in name)
                    or (
                        metadata.get("parents")
                        and (body.folder or "root") != "root"
                        and body.folder not in metadata["parents"]
                    )
                ):
                    continue
                guard()
                content = client.download(file_id, mime)
                guard()
                if not content or len(content) > MAX_BYTES:
                    raise ValueError("Drive snapshot limit")
                yield Document(file_id + "/" + name, content)
                count += 1
                if count >= body.max_files:
                    return
            page = response.get("next_page_token", "")
            if not page:
                return
        raise ValueError("Drive listing limit")


def _transfer_view(row: GoogleDriveTransfer, revision: int | None = None) -> dict[str, Any]:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "request_id",
            "operation",
            "status",
            "remote_id",
            "folder_id",
            "artifact_id",
            "artifact_revision",
            "name",
            "size",
            "created",
            "error",
        )
    } | {"integration_revision": revision or row.profile_revision}


def _artifact_bytes(
    db: Session, cfg: Settings, artifact_id: str, revision: int
) -> tuple[bytes, str, str]:
    artifact = db.get(Artifact, artifact_id, populate_existing=True)
    row = db.get(ArtifactRevision, (artifact_id, revision), populate_existing=True)
    if not artifact or not row:
        raise ValueError("Gewählte Dateiversion fehlt oder wurde inzwischen geändert")
    owner(db, artifact.project_id, artifact.conversation_id)
    if row.status not in {"needs_review", "published"} or not row.manifest:
        raise ValueError("Datei ist noch nicht vollständig erstellt")
    manifest = checked_manifest(cfg, row, row.manifest)
    spec = spec_for(row)
    bind_sources(db, cfg, artifact.project_id, spec, conversation_id=artifact.conversation_id)
    content = output_file(cfg, row, manifest.filename, manifest.sha256).read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest.sha256:
        raise ValueError("Datei wurde zwischen Prüfung und Übertragung verändert")
    if len(content) > 25 * 1024 * 1024:
        raise ValueError("Google-Drive-Ablage unterstützt Dateien bis 25 MiB")
    suffix = PurePosixPath(manifest.filename).suffix
    title = re.sub(r"[\\/:\x00-\x1f\x7f]", "_", spec.plan.title).strip(" .")[:180]
    name = (title or "obdaAI-Datei") + suffix
    return content, name, mimetypes.guess_type(manifest.filename)[0] or "application/octet-stream"


def _write_profile(
    factory: sessionmaker[Session], cfg: Settings, identifier: str, revision: int
) -> dict[str, Any]:
    from hub.google_drive_setup import authority_guard

    authority_guard(factory, cfg, identifier, revision, "storage")()
    with factory() as db:
        row = db.get(Integration, identifier, populate_existing=True)
        if not row or row.revision != revision:
            raise ValueError("Drive connection changed")
        config = json.loads(row.config)
        if not isinstance(config, dict):
            raise ValueError("Invalid Drive configuration")
        return config


def execute_transfer(
    factory: sessionmaker[Session],
    cfg: Settings,
    integration_id: str,
    body: DriveFolderInput | DriveExportInput,
    operation: str,
) -> dict[str, Any]:
    from hub.google_drive_client import DriveClient
    from hub.google_drive_setup import access_token, authority_guard

    revision = body.expected_revision
    if operation == "export" and (
        not isinstance(body, DriveExportInput) or not body.cloud_upload_approved
    ):
        raise ValueError("Die Übertragung dieser konkreten Datei an Google ausdrücklich freigeben")
    with factory() as db:
        previous = db.scalar(
            select(GoogleDriveTransfer).where(
                GoogleDriveTransfer.request_id == str(body.request_id)
            )
        )
        if previous:
            expected = digest(
                encode(
                    {
                        "integration_id": integration_id,
                        "operation": operation,
                        **body.model_dump(mode="json"),
                        "folder_id": previous.folder_id,
                        "sha256": previous.content_sha256,
                    }
                )
            )
            if previous.request_digest != expected:
                raise ValueError("Auftragskennung gehört zu einer anderen Übertragung")
            if previous.status in {"succeeded", "failed", "preparing"}:
                current_profile = db.get(Integration, integration_id)
                return _transfer_view(
                    previous, current_profile.revision if current_profile else None
                )
    config = _write_profile(factory, cfg, integration_id, revision)
    content, name, mime, folder = b"", "obdaAI", FOLDER_MIME, ""
    if isinstance(body, DriveExportInput):
        folder = config.get("storage_folder_id", "")
        if not _ID.fullmatch(folder):
            raise ValueError("Zuerst einen obdaAI-Ablageordner erstellen")
        with factory() as db:
            content, name, mime = _artifact_bytes(
                db, cfg, str(body.artifact_id), body.artifact_revision
            )
    request_digest = digest(
        encode(
            {
                "integration_id": integration_id,
                "operation": operation,
                **body.model_dump(mode="json"),
                "folder_id": folder,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    )
    with factory() as db:
        ownership_lock(db)
        row = db.scalar(
            select(GoogleDriveTransfer).where(
                GoogleDriveTransfer.request_id == str(body.request_id)
            )
        )
        if row:
            if row.request_digest != request_digest:
                raise ValueError("Auftragskennung gehört zu einer anderen Übertragung")
            if row.status in {"succeeded", "failed", "preparing"}:
                return _transfer_view(row)
            transfer_id = row.id
            reconcile_only = True
        else:
            pending = db.scalar(
                select(GoogleDriveTransfer).where(
                    GoogleDriveTransfer.integration_id == integration_id,
                    GoogleDriveTransfer.operation == operation,
                    GoogleDriveTransfer.status.in_(["preparing", "dispatching", "uncertain"]),
                )
            )
            if pending:
                raise ValueError("Vorhandenen unklaren Auftrag zuerst prüfen; nicht erneut senden")
            if operation == "folder" and config.get("storage_folder_id"):
                raise ValueError("Ein obdaAI-Ablageordner ist bereits eingerichtet")
            row = GoogleDriveTransfer(
                request_id=str(body.request_id),
                request_digest=request_digest,
                integration_id=integration_id,
                profile_revision=revision,
                operation=operation,
                name=name,
                mime_type=mime,
                folder_id=folder,
                artifact_id=str(body.artifact_id) if isinstance(body, DriveExportInput) else None,
                artifact_revision=body.artifact_revision
                if isinstance(body, DriveExportInput)
                else None,
                content_sha256=hashlib.sha256(content).hexdigest(),
                content_md5=hashlib.md5(content, usedforsecurity=False).hexdigest(),
                size=len(content),
            )
            db.add(row)
            db.flush()
            transfer_id = row.id
            db.commit()
            reconcile_only = False

    def guard() -> None:
        authority_guard(factory, cfg, integration_id, revision, "storage")()
        if isinstance(body, DriveExportInput):
            with factory() as db:
                fresh, _, _ = _artifact_bytes(
                    db, cfg, str(body.artifact_id), body.artifact_revision
                )
                if hashlib.sha256(fresh).hexdigest() != hashlib.sha256(content).hexdigest():
                    raise ValueError("Dateiversion wurde verändert")
        fresh_config = _write_profile(factory, cfg, integration_id, revision)
        if operation == "export" and fresh_config.get("storage_folder_id") != folder:
            raise ValueError("Ablageordner wurde geändert")

    try:
        token = access_token(
            factory, cfg, integration_id, revision, capability="storage", before_send=guard
        )
        with DriveClient(token, before_send=guard) as client:
            if operation == "export":
                with factory() as db:
                    folder_receipt = db.scalar(
                        select(GoogleDriveTransfer).where(
                            GoogleDriveTransfer.integration_id == integration_id,
                            GoogleDriveTransfer.operation == "folder",
                            GoogleDriveTransfer.status == "succeeded",
                            GoogleDriveTransfer.remote_id == folder,
                        )
                    )
                    if not folder_receipt:
                        raise ValueError("Ablageordner besitzt keinen verifizierten obdaAI-Auftrag")
                    folder_transfer_id = folder_receipt.id
                folder_metadata = client.metadata(folder)
                if not (
                    folder_metadata.get("id") == folder
                    and folder_metadata.get("mimeType") == FOLDER_MIME
                    and not folder_metadata.get("trashed", False)
                    and folder_metadata.get("ownedByMe") is True
                    and folder_metadata.get("capabilities", {}).get("canAddChildren") is True
                    and folder_metadata.get("appProperties", {}).get("obdaai_integration")
                    == integration_id
                    and folder_metadata.get("appProperties", {}).get("obdaai_transfer")
                    == folder_transfer_id
                ):
                    raise ValueError("Ablageordner ist nicht mehr aktuell für obdaAI freigegeben")
            with factory() as db:
                current = db.get(GoogleDriveTransfer, transfer_id)
                assert current
                remote_id = current.remote_id
            if not reconcile_only:
                remote_id = client.generate_ids(count=1)[0]
                with factory() as db:
                    ownership_lock(db)
                    current = db.get(GoogleDriveTransfer, transfer_id)
                    assert current and current.status == "preparing"
                    current.remote_id, current.status, current.updated = (
                        remote_id,
                        "dispatching",
                        time.time(),
                    )
                    db.commit()
                guard()
                props = {"obdaai_transfer": transfer_id, "obdaai_integration": integration_id}
                if operation == "folder":
                    metadata = client.create_folder(remote_id, name, app_properties=props)
                else:
                    metadata = client.upload(
                        remote_id, folder, name, content, mime, app_properties=props
                    )
            else:
                if not remote_id:
                    raise ValueError("Unklare Übertragung besitzt keine verifizierbare Google-ID")
                metadata = client.metadata(remote_id)
            guard()
            if (
                metadata.get("id") != remote_id
                or metadata.get("name") != name
                or metadata.get("mimeType") != mime
                or metadata.get("trashed", False)
                or metadata.get("appProperties", {}).get("obdaai_transfer") != transfer_id
                or metadata.get("appProperties", {}).get("obdaai_integration") != integration_id
                or operation == "export"
                and (
                    folder not in metadata.get("parents", [])
                    or int(metadata.get("size", -1)) != len(content)
                    or metadata.get("md5Checksum")
                    != hashlib.md5(content, usedforsecurity=False).hexdigest()
                )
            ):
                raise ValueError("Google-Datei stimmt nicht mit dem Übertragungsauftrag überein")
            with factory() as db:
                ownership_lock(db)
                current = db.get(GoogleDriveTransfer, transfer_id)
                profile = db.get(Integration, integration_id, populate_existing=True)
                assert current
                if current.status == "succeeded":
                    return _transfer_view(current, profile.revision if profile else None)
                if not profile or profile.revision != revision:
                    raise ValueError("Drive-Verbindung wurde vor Abschluss geändert")
                if operation == "folder":
                    data = json.loads(profile.config)
                    data["storage_folder_id"] = remote_id
                    profile.config = encode(data)
                    profile.revision += 1
                    db.flush()
                    rebind_source_revision(db, integration_id, revision, profile.revision)
                current.status, current.error, current.updated = "succeeded", "", time.time()
                db.commit()
                return _transfer_view(current, profile.revision)
    except Exception:
        with factory() as db:
            ownership_lock(db)
            current = db.get(GoogleDriveTransfer, transfer_id, populate_existing=True)
            assert current
            if current.status == "succeeded":
                profile = db.get(Integration, integration_id, populate_existing=True)
                return _transfer_view(current, profile.revision if profile else None)
            current.status = "uncertain" if current.remote_id else "failed"
            current.error, current.updated = "google_transfer_unconfirmed", time.time()
            db.commit()
            return _transfer_view(current)


def reconcile_transfer(
    factory: sessionmaker[Session],
    cfg: Settings,
    integration_id: str,
    transfer_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Read only the durable remote identity; never regenerate or redispatch a write.

    Local artifact bytes are deliberately unnecessary: Google already received the
    original dispatch (possibly). Compare its stored hash/identity receipt instead.
    A revoked authority or racing successful reader never downgrades durable state.
    """
    from hub.google_drive_client import DriveClient
    from hub.google_drive_setup import access_token, authority_guard, ready

    with factory() as db:
        row = db.get(GoogleDriveTransfer, transfer_id)
        if not row or row.integration_id != integration_id:
            raise ValueError("Übertragungsauftrag fehlt")
        profile = db.get(Integration, integration_id)
        if row.status != "uncertain" or not row.remote_id:
            return _transfer_view(row, profile.revision if profile else None)
        target = {
            key: getattr(row, key)
            for key in (
                "id",
                "request_digest",
                "profile_revision",
                "operation",
                "remote_id",
                "folder_id",
                "name",
                "mime_type",
                "size",
                "content_md5",
            )
        }
    try:
        if target["profile_revision"] != expected_revision:
            raise PermissionError("Ursprüngliche Drive-Freigabe wurde geändert")
        guard = authority_guard(factory, cfg, integration_id, expected_revision, "storage")
        guard()
        token = access_token(
            factory, cfg, integration_id, expected_revision, capability="storage", before_send=guard
        )
        with DriveClient(token, before_send=guard) as client:
            metadata = client.metadata(target["remote_id"])
        guard()
        if (
            metadata.get("id") != target["remote_id"]
            or metadata.get("name") != target["name"]
            or metadata.get("mimeType") != target["mime_type"]
            or metadata.get("trashed", False)
            or metadata.get("appProperties", {}).get("obdaai_transfer") != transfer_id
            or metadata.get("appProperties", {}).get("obdaai_integration") != integration_id
        ):
            raise ValueError("Google-Identität passt nicht zum gespeicherten Auftrag")
        if target["operation"] == "export":
            if (
                target["folder_id"] not in metadata.get("parents", [])
                or int(metadata.get("size", -1)) != target["size"]
                or metadata.get("md5Checksum") != target["content_md5"]
            ):
                raise ValueError("Google-Dateiprüfsumme oder Zielordner stimmt nicht überein")
        elif target["operation"] == "folder":
            if not (
                metadata.get("mimeType") == FOLDER_MIME
                and metadata.get("ownedByMe") is True
                and metadata.get("capabilities", {}).get("canAddChildren") is True
            ):
                raise ValueError("Google-Ordner ist nicht mehr als eigene Ablage freigegeben")
        else:
            raise ValueError("Ungültiger Übertragungsauftrag")
        with factory() as db:
            ownership_lock(db)
            row = db.get(GoogleDriveTransfer, transfer_id, populate_existing=True)
            profile = db.get(Integration, integration_id, populate_existing=True)
            assert row
            if row.status == "succeeded":
                return _transfer_view(row, profile.revision if profile else None)
            if (
                row.status != "uncertain"
                or row.remote_id != target["remote_id"]
                or row.request_digest != target["request_digest"]
                or not profile
                or profile.revision != expected_revision
                or not ready(cfg, profile, "storage")
            ):
                raise PermissionError("Drive-Freigabe vor Abschluss geändert")
            if target["operation"] == "folder":
                config = json.loads(profile.config)
                if config.get("storage_folder_id") not in (None, "", target["remote_id"]):
                    raise ValueError("Eine andere Ablage wurde zwischenzeitlich eingerichtet")
                config["storage_folder_id"] = target["remote_id"]
                profile.config = encode(config)
                profile.revision += 1
                db.flush()
                rebind_source_revision(db, integration_id, expected_revision, profile.revision)
            row.status, row.error, row.updated = "succeeded", "", time.time()
            db.commit()
            return _transfer_view(row, profile.revision)
    except Exception:
        # This read cannot undo a previously verified success and grants no new
        # rights when configuration/account/permission has changed meanwhile.
        with factory() as db:
            row = db.get(GoogleDriveTransfer, transfer_id, populate_existing=True)
            profile = db.get(Integration, integration_id, populate_existing=True)
            assert row
            result = _transfer_view(row, profile.revision if profile else None)
            if row.status != "succeeded":
                result["message"] = (
                    "Status nicht bestätigt; ursprünglichen Auftrag nicht erneut senden."
                )
            return result


def install_google_drive_files(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/integrations/google-drive/{integration_id}/files")
    def files(
        integration_id: UUID, auth: Auth, parent_id: str = "root", page_token: str = ""
    ) -> dict[str, Any]:
        from hub.google_drive_client import DriveClient
        from hub.google_drive_setup import access_token, authority_guard

        if not _ID.fullmatch(parent_id) or len(page_token) > 512:
            raise HTTPException(422, "Ungültiger Drive-Ordner")
        try:
            with factory() as db:
                row = db.get(Integration, str(integration_id))
                if not row:
                    raise ValueError("Drive-Verbindung fehlt")
                revision = row.revision
                root = json.loads(row.config).get("source_folder_id") or "root"
            guard = authority_guard(factory, cfg, str(integration_id), revision, "source")
            token = access_token(
                factory, cfg, str(integration_id), revision, capability="source", before_send=guard
            )
            with DriveClient(token, before_send=guard) as client:
                if root != "root" and parent_id != root:
                    # An explicitly scoped folder cannot be escaped via a forged browser request.
                    meta = client.metadata(parent_id)
                    if root not in meta.get("parents", []):
                        raise ValueError("Ordner außerhalb des gewählten Quellenbereichs")
                return client.list_files(parent=parent_id, page_token=page_token, limit=50)
        except (ValueError, OSError):
            raise HTTPException(
                409, "Google Drive ist nicht verbunden oder der Ordner nicht freigegeben"
            ) from None

    @app.post("/api/integrations/google-drive/{integration_id}/source")
    def source(integration_id: UUID, body: DriveSourceInput, auth: Auth) -> dict[str, Any]:
        from hub.google_drive_client import DriveClient
        from hub.google_drive_setup import access_token, authority_guard

        try:
            guard = authority_guard(
                factory, cfg, str(integration_id), body.expected_revision, "source"
            )
            guard()
            with factory() as db:
                profile = db.get(Integration, str(integration_id), populate_existing=True)
                if not profile or profile.revision != body.expected_revision:
                    raise ValueError("Drive-Verbindung geändert")
                configured_folder = json.loads(profile.config).get("source_folder_id") or "root"
                if configured_folder != "root" and configured_folder != body.folder_id:
                    raise ValueError("Ordner außerhalb des gewählten Quellenbereichs")
            if body.folder_id != "root":
                token = access_token(
                    factory,
                    cfg,
                    str(integration_id),
                    body.expected_revision,
                    capability="source",
                    before_send=guard,
                )
                with DriveClient(token, before_send=guard) as client:
                    metadata = client.metadata(body.folder_id)
                    if (
                        metadata.get("id") != body.folder_id
                        or metadata.get("mimeType") != FOLDER_MIME
                        or metadata.get("trashed", False)
                    ):
                        raise ValueError("Gewählte Quelle ist kein aktueller Drive-Ordner")
            guard()
            with factory() as db:
                ownership_lock(db)
                integration = db.get(Integration, str(integration_id), populate_existing=True)
                if not integration or integration.revision != body.expected_revision:
                    raise ValueError("Drive-Verbindung geändert")
                source_body = ConnectionInput(
                    name=integration.name,
                    kind="google_drive",
                    server="www.googleapis.com",
                    folder=body.folder_id,
                    integration_id=integration_id,
                    integration_revision=integration.revision,
                    max_files=body.max_files,
                )
                validate_source(db, source_body)
                row = db.scalar(
                    select(KnowledgeConnection).where(
                        KnowledgeConnection.kind == "google_drive",
                        KnowledgeConnection.target_ref == str(integration_id),
                    )
                )
                if not row:
                    project = Project(name=integration.name, kind="knowledge")
                    db.add(project)
                    db.flush()
                    row = KnowledgeConnection(
                        name=integration.name,
                        kind="google_drive",
                        address="drive.google.com",
                        target_ref=str(integration_id),
                        project_id=project.id,
                        enabled=False,
                        config=encode(source_body.public()),
                    )
                    db.add(row)
                    db.flush()
                elif row.status == "indexing":
                    raise ValueError("Laufenden Abgleich zuerst beenden lassen")
                else:
                    previous = ConnectionInput.model_validate_json(row.config)
                    if (
                        previous.folder != source_body.folder
                        or previous.integration_revision != source_body.integration_revision
                        or previous.integration_id != source_body.integration_id
                    ):
                        # Preserve old bytes/history but never mix a prior folder/account into
                        # the newly selected source. Revision invalidates in-flight extraction.
                        for snapshot in db.scalars(
                            select(Source).where(
                                Source.project_id == row.project_id,
                                Source.status.notin_(["superseded", "deleted"]),
                            )
                        ):
                            snapshot.status = "superseded"
                            snapshot.revision += 1
                    row.name, row.config = integration.name, encode(source_body.public())
                    row.revision += 1
                    row.status = "needs_setup"
                db.commit()
                from hub.knowledge_connections import info

                return info(db, row) | {"connection_id": row.id}
        except (ValueError, OSError):
            raise HTTPException(
                409, "Google-Drive-Quelle wurde geändert oder ist nicht freigegeben"
            ) from None

    @app.post("/api/integrations/google-drive/{integration_id}/storage-folder")
    def storage_folder(integration_id: UUID, body: DriveFolderInput, auth: Auth) -> dict[str, Any]:
        try:
            return execute_transfer(factory, cfg, str(integration_id), body, "folder")
        except (ValueError, OSError):
            raise HTTPException(
                409, "Ablageauftrag nicht möglich; Verbindung und Freigabe prüfen"
            ) from None

    @app.post("/api/integrations/google-drive/{integration_id}/export")
    def export(integration_id: UUID, body: DriveExportInput, auth: Auth) -> dict[str, Any]:
        try:
            return execute_transfer(factory, cfg, str(integration_id), body, "export")
        except (ValueError, OSError):
            raise HTTPException(
                409, "Dateiübertragung nicht möglich; aktuelle Version und Freigabe prüfen"
            ) from None

    @app.post("/api/integrations/google-drive/{integration_id}/exports/{transfer_id}/reconcile")
    def reconcile_export(
        integration_id: UUID, transfer_id: UUID, body: DriveReconcileInput, auth: Auth
    ) -> dict[str, Any]:
        try:
            return reconcile_transfer(
                factory, cfg, str(integration_id), str(transfer_id), body.expected_revision
            )
        except (ValueError, OSError):
            raise HTTPException(409, "Übertragungsauftrag konnte nicht geprüft werden") from None

    @app.get("/api/integrations/google-drive/{integration_id}/exports")
    def exports(integration_id: UUID, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            return [
                _transfer_view(row)
                for row in db.scalars(
                    select(GoogleDriveTransfer)
                    .where(GoogleDriveTransfer.integration_id == str(integration_id))
                    .order_by(GoogleDriveTransfer.created.desc())
                    .limit(50)
                )
            ]
