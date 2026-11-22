"""Synthetic Drive source and durable write-boundary acceptance; no real Google account."""

import asyncio
import base64
import hashlib
import json
import os
import time
import uuid
from dataclasses import replace

import pytest
from hub.config import Settings
from hub.db import Base, KnowledgeConnection, Project, Source
from hub.google_drive_client import API_BASE, READ_SCOPE, WRITE_SCOPE
from hub.google_drive_files import (
    FOLDER_MIME,
    DriveExportInput,
    DriveFolderInput,
    GoogleDriveTransfer,
    drive_documents,
    execute_transfer,
    source_enabled,
)
from hub.google_drive_setup import MARKER
from hub.integrations import Integration
from hub.knowledge_clients import ConnectionInput
from hub.knowledge_connections import check_chat_source, index_connection
from hub.provider_settings import encrypt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def setup(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    key = tmp_path / "key"
    key.write_bytes(base64.b64encode(os.urandom(32)))
    key.chmod(0o600)
    cfg = Settings(
        secrets_key_file=str(key),
        integration_targets_enabled=True,
        source_dir=str(tmp_path / "sources"),
    )
    with factory() as db:
        integration = Integration(
            id=str(uuid.uuid4()),
            name="Synthetic Drive",
            kind="google_drive",
            enabled=True,
            writes_enabled=True,
            config=json.dumps(
                {
                    "url": API_BASE,
                    "auth": "oauth",
                    "google_drive_marker": MARKER,
                    "connected": True,
                    "enable_source": True,
                    "enable_storage": True,
                    "source_folder_id": "source-folder",
                    "account_email": "synthetic@example.invalid",
                    "scope": " ".join(sorted([READ_SCOPE, WRITE_SCOPE])),
                }
            ),
        )
        integration.encrypted_secret = encrypt(
            cfg,
            "integration:" + integration.id,
            json.dumps(
                {
                    "access_token": "synthetic-drive-token",
                    "refresh_token": "synthetic-refresh",
                    "expires_at": time.time() + 3600,
                    "token_type": "Bearer",
                    "scope": " ".join(sorted([READ_SCOPE, WRITE_SCOPE])),
                    "account_email": "synthetic@example.invalid",
                }
            ),
        )
        db.add(integration)
        project = Project(name="Synthetic Drive knowledge", kind="knowledge")
        db.add(project)
        db.flush()
        body = ConnectionInput(
            name=integration.name,
            kind="google_drive",
            server="www.googleapis.com",
            folder="source-folder",
            integration_id=integration.id,
            integration_revision=1,
        )
        connection = KnowledgeConnection(
            name=integration.name,
            kind="google_drive",
            project_id=project.id,
            target_ref=integration.id,
            config=json.dumps(body.public()),
            enabled=True,
            status="indexing",
        )
        db.add(connection)
        db.commit()
    yield factory, cfg, integration.id, connection.id, body
    engine.dispose()


class FakeDrive:
    files = []
    calls = []
    stored = {}
    lose_response = False
    generation = 0

    def __init__(self, token, before_send=None):
        assert token == "synthetic-drive-token"
        self.guard = before_send

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def list_files(self, parent, **kwargs):
        self.guard()
        assert parent == self.allowed_parent
        return {"files": self.files}

    def download(self, file_id, mime_type):
        self.guard()
        return b"Synthetic DRIVE_SOURCE_SEVEN"

    def generate_ids(self, count=1):
        self.guard()
        type(self).generation += 1
        return ["generated-" + str(self.generation)]

    def create_folder(self, file_id, name, app_properties):
        self.guard()
        self.calls.append(("POST-folder", file_id))
        metadata = {
            "id": file_id,
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "appProperties": app_properties,
            "ownedByMe": True,
            "capabilities": {"canAddChildren": True},
        }
        self.stored[file_id] = metadata
        if self.lose_response:
            raise ValueError("Synthetic uncertain transport")
        return metadata

    def upload(self, file_id, parent, name, content, mime_type, app_properties):
        self.guard()
        self.calls.append(("POST-upload", file_id))
        metadata = {
            "id": file_id,
            "name": name,
            "mimeType": mime_type,
            "parents": [parent],
            "appProperties": app_properties,
            "size": str(len(content)),
            "md5Checksum": hashlib.md5(content, usedforsecurity=False).hexdigest(),
        }
        self.stored[file_id] = metadata
        if self.lose_response:
            raise ValueError("Synthetic uncertain transport")
        return metadata

    def metadata(self, file_id):
        self.guard()
        self.calls.append(("GET", file_id))
        return self.stored[file_id]


@pytest.fixture
def fake(monkeypatch):
    FakeDrive.allowed_parent = "source-folder"
    FakeDrive.files = [
        {
            "id": "file-one",
            "name": "evidence.txt",
            "mimeType": "text/plain",
            "parents": ["source-folder"],
        }
    ]
    FakeDrive.calls, FakeDrive.stored = (
        [],
        {
            "source-folder": {
                "id": "source-folder",
                "name": "Synthetic source",
                "mimeType": "application/vnd.google-apps.folder",
                "trashed": False,
            }
        },
    )
    FakeDrive.lose_response, FakeDrive.generation = False, 0
    monkeypatch.setattr("hub.google_drive_client.DriveClient", FakeDrive)
    return FakeDrive


def test_source_iterator_and_existing_snapshot_index_keep_local_scope(setup, fake, monkeypatch):
    factory, cfg, identifier, connection_id, body = setup
    docs = list(drive_documents(factory, cfg, body))
    assert docs[0].path == "file-one/evidence.txt" and b"DRIVE_SOURCE_SEVEN" in docs[0].content

    async def no_extract(*args):
        pass

    monkeypatch.setattr("hub.knowledge_connections.extract_source", no_extract)
    asyncio.run(index_connection(factory, cfg, connection_id, 1))
    with factory() as db:
        connection = db.get(KnowledgeConnection, connection_id)
        row = db.scalar(select(Source).where(Source.project_id == connection.project_id))
        assert row and row.label == "LOCAL_ONLY" and connection.status == "ready"
        row.status = "ready"
        db.commit()
        check_chat_source(db, connection.project_id)
        cached = db.get(Integration, identifier)
        with factory() as other:
            other.get(Integration, identifier).enabled = False
            other.commit()
        assert cached.enabled  # Ensure the read path does not trust the identity cache.
        assert not source_enabled(db, connection)
        with pytest.raises(ValueError):
            check_chat_source(db, connection.project_id)


def test_source_cannot_escape_configured_folder_or_revision(setup, fake):
    factory, cfg, identifier, _, body = setup
    for changes in [{"folder": "another-folder"}, {"integration_revision": 2}]:
        altered = body.model_copy(update=changes)
        with pytest.raises((ValueError, PermissionError)):
            list(drive_documents(factory, cfg, altered))


def test_native_export_mapping_and_shortcuts_not_followed(setup, fake):
    factory, cfg, _, _, body = setup
    fake.files = [
        {
            "id": "shortcut",
            "name": "private-link",
            "mimeType": "application/vnd.google-apps.shortcut",
        },
        {
            "id": "document",
            "name": "Native",
            "mimeType": "application/vnd.google-apps.document",
            "parents": ["source-folder"],
        },
    ]
    rows = list(drive_documents(factory, cfg, body))
    assert [row.path for row in rows] == ["document/Native.docx"]


def test_folder_intent_is_idempotent_and_updates_revision_only_after_verification(setup, fake):
    factory, cfg, identifier, _, _ = setup
    body = DriveFolderInput(expected_revision=1, request_id=uuid.uuid4())
    first = execute_transfer(factory, cfg, identifier, body, "folder")
    assert first["status"] == "succeeded" and first["integration_revision"] == 2
    assert execute_transfer(factory, cfg, identifier, body, "folder")["id"] == first["id"]
    assert len(fake.calls) == 1
    with factory() as db:
        row = db.get(Integration, identifier)
        assert json.loads(row.config)["storage_folder_id"] == first["remote_id"]


def test_lost_folder_reply_is_reconciled_by_get_never_second_post(setup, fake):
    factory, cfg, identifier, _, _ = setup
    body = DriveFolderInput(expected_revision=1, request_id=uuid.uuid4())
    fake.lose_response = True
    unknown = execute_transfer(factory, cfg, identifier, body, "folder")
    assert unknown["status"] == "uncertain"
    with pytest.raises(ValueError):
        execute_transfer(
            factory,
            cfg,
            identifier,
            DriveFolderInput(expected_revision=1, request_id=uuid.uuid4()),
            "folder",
        )
    fresh = execute_transfer(factory, cfg, identifier, body, "folder")
    assert fresh["status"] == "succeeded"
    assert [kind for kind, _ in fake.calls] == ["POST-folder", "GET"]


def test_export_requires_per_file_transfer_approval_before_token_or_http(setup, fake):
    factory, cfg, identifier, _, _ = setup
    with pytest.raises(ValueError):
        execute_transfer(
            factory,
            cfg,
            identifier,
            DriveExportInput(
                expected_revision=1,
                request_id=uuid.uuid4(),
                artifact_id=uuid.uuid4(),
                artifact_revision=1,
            ),
            "export",
        )
    assert fake.calls == []
    with factory() as db:
        assert db.scalar(select(GoogleDriveTransfer)) is None


def test_export_pins_bytes_folder_and_reconciles_uncertain_delivery(setup, fake, monkeypatch):
    factory, cfg, identifier, _, _ = setup
    folder = execute_transfer(
        factory,
        cfg,
        identifier,
        DriveFolderInput(expected_revision=1, request_id=uuid.uuid4()),
        "folder",
    )
    assert folder["status"] == "succeeded"
    fake.calls.clear()
    monkeypatch.setattr(
        "hub.google_drive_files._artifact_bytes",
        lambda *args: (b"synthetic artifact", "Synthetic.pdf", "application/pdf"),
    )
    body = DriveExportInput(
        expected_revision=2,
        request_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        artifact_revision=1,
        cloud_upload_approved=True,
    )
    fake.lose_response = True
    unknown = execute_transfer(factory, cfg, identifier, body, "export")
    assert unknown["status"] == "uncertain"
    completed = execute_transfer(factory, cfg, identifier, body, "export")
    assert completed["status"] == "succeeded" and completed["size"] == 18
    assert [kind for kind, _ in fake.calls] == ["GET", "POST-upload", "GET", "GET"]
    with factory() as db:
        row = db.get(GoogleDriveTransfer, completed["id"])
        assert row.content_sha256 == hashlib.sha256(b"synthetic artifact").hexdigest()
        assert "synthetic-drive-token" not in json.dumps(completed)


def test_revoked_storage_rights_before_effect_produce_no_upload(setup, fake):
    factory, cfg, identifier, _, _ = setup
    original = fake.generate_ids

    def revoke(self, count=1):
        ids = original(self, count)
        with factory() as db:
            db.get(Integration, identifier).enabled = False
            db.commit()
        return ids

    fake.generate_ids = revoke
    try:
        result = execute_transfer(
            factory,
            cfg,
            identifier,
            DriveFolderInput(expected_revision=1, request_id=uuid.uuid4()),
            "folder",
        )
        assert result["status"] == "uncertain"
        assert fake.calls == []
    finally:
        fake.generate_ids = original


def test_corrupt_folder_receipt_is_not_accepted_or_recreated(setup, fake):
    factory, cfg, identifier, _, _ = setup
    original = fake.create_folder

    def corrupt(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        result["appProperties"]["obdaai_integration"] = "different-integration"
        return result

    fake.create_folder = corrupt
    body = DriveFolderInput(expected_revision=1, request_id=uuid.uuid4())
    try:
        result = execute_transfer(factory, cfg, identifier, body, "folder")
        assert result["status"] == "uncertain"
        with factory() as db:
            assert not json.loads(db.get(Integration, identifier).config).get("storage_folder_id")
        assert execute_transfer(factory, cfg, identifier, body, "folder")["status"] == "uncertain"
        assert [kind for kind, _ in fake.calls] == ["POST-folder", "GET"]
    finally:
        fake.create_folder = original


@pytest.fixture
def real_artifact(tmp_path, monkeypatch):
    import test_artifact_api

    yield from test_artifact_api.setup.__wrapped__(tmp_path, monkeypatch)


def test_real_rendered_artifact_export_preserves_local_bytes_and_scope(real_artifact, fake):
    import test_artifact_api
    from hub.db import ArtifactRevision

    app, client, headers, original_cfg, project_id, spec = real_artifact
    cfg = replace(original_cfg, integration_targets_enabled=True)
    factory = app.state.sessions
    with factory() as db:
        identifier = str(uuid.uuid4())
        scopes = " ".join(sorted([READ_SCOPE, WRITE_SCOPE]))
        row = Integration(
            id=identifier,
            name="Synthetic artifact Drive",
            kind="google_drive",
            enabled=True,
            writes_enabled=True,
            config=json.dumps(
                {
                    "url": API_BASE,
                    "auth": "oauth",
                    "google_drive_marker": MARKER,
                    "connected": True,
                    "enable_source": True,
                    "enable_storage": True,
                    "source_folder_id": "root",
                    "scope": scopes,
                    "account_email": "synthetic@example.invalid",
                }
            ),
        )
        row.encrypted_secret = encrypt(
            cfg,
            "integration:" + identifier,
            json.dumps(
                {
                    "access_token": "synthetic-drive-token",
                    "refresh_token": "synthetic-refresh",
                    "expires_at": time.time() + 3600,
                    "token_type": "Bearer",
                    "scope": scopes,
                    "account_email": "synthetic@example.invalid",
                }
            ),
        )
        db.add(row)
        db.commit()
    rendered = test_artifact_api.create(client, headers, project_id, spec).json()
    rendered = test_artifact_api.pump(app, client, cfg, project_id, rendered)
    assert rendered["status"] == "needs_review"
    original = client.get(test_artifact_api.base(project_id, rendered) + "/download").content
    folder = execute_transfer(
        factory,
        cfg,
        identifier,
        DriveFolderInput(expected_revision=1, request_id=uuid.uuid4()),
        "folder",
    )
    assert folder["status"] == "succeeded"
    body = DriveExportInput(
        expected_revision=2,
        request_id=uuid.uuid4(),
        artifact_id=rendered["artifact_id"],
        artifact_revision=1,
        cloud_upload_approved=True,
    )
    result = execute_transfer(factory, cfg, identifier, body, "export")
    assert result["status"] == "succeeded" and result["size"] == len(original)
    assert (
        client.get(test_artifact_api.base(project_id, rendered) + "/download").content == original
    )
    with factory() as db:
        artifact = db.get(ArtifactRevision, (rendered["artifact_id"], 1))
        assert artifact.status == "needs_review" and artifact.accepted is None
        transfer = db.get(GoogleDriveTransfer, result["id"])
        assert transfer.content_sha256 == hashlib.sha256(original).hexdigest()
        assert (
            json.loads(db.get(Integration, identifier).config)["storage_folder_id"]
            == result["folder_id"]
        )


def test_storage_folder_success_rebinds_unchanged_source_without_reimport(setup, fake):
    factory, cfg, identifier, connection_id, _ = setup
    with factory() as db:
        connection = db.get(KnowledgeConnection, connection_id)
        connection.status = "ready"
        db.add(
            Source(
                project_id=connection.project_id,
                name="old.txt",
                sha256="a" * 64,
                status="ready",
                size=3,
            )
        )
        db.commit()
    result = execute_transfer(
        factory,
        cfg,
        identifier,
        DriveFolderInput(expected_revision=1, request_id=uuid.uuid4()),
        "folder",
    )
    assert result["status"] == "succeeded"
    with factory() as db:
        connection = db.get(KnowledgeConnection, connection_id)
        assert connection.status == "ready" and source_enabled(db, connection)
        assert json.loads(connection.config)["integration_revision"] == 2
        assert len(list(db.scalars(select(Source)))) == 1
        check_chat_source(db, connection.project_id)


@pytest.mark.parametrize("existing_ready", [False, True])
def test_source_neutral_control_rebind_invalidates_old_index_but_preserves_snapshots(
    setup, existing_ready
):
    from hub.google_drive_files import rebind_source_revision

    factory, cfg, identifier, connection_id, _ = setup
    with factory() as db:
        connection = db.get(KnowledgeConnection, connection_id)
        if existing_ready:
            db.add(
                Source(
                    project_id=connection.project_id,
                    name="old.txt",
                    sha256="a" * 64,
                    status="ready",
                    size=3,
                )
            )
        profile = db.get(Integration, identifier)
        profile.enabled = False
        profile.revision = 2
        db.flush()
        rebind_source_revision(db, identifier, 1, 2)
        db.commit()
        assert not source_enabled(db, connection)
        assert connection.revision == 2 and connection.status == (
            "ready" if existing_ready else "needs_setup"
        )
        profile.enabled = True
        profile.revision = 3
        db.flush()
        rebind_source_revision(db, identifier, 2, 3)
        db.commit()
        assert source_enabled(db, connection)
        assert connection.revision == 3
        assert len(list(db.scalars(select(Source)))) == int(existing_ready)


def test_source_rebind_does_not_upgrade_changed_source_folder(setup):
    from hub.google_drive_files import rebind_source_revision

    factory, cfg, identifier, connection_id, _ = setup
    with factory() as db:
        profile = db.get(Integration, identifier)
        config = json.loads(profile.config)
        config["source_folder_id"] = "different-folder"
        profile.config, profile.revision = json.dumps(config), 2
        db.flush()
        rebind_source_revision(db, identifier, 1, 2)
        db.commit()
        connection = db.get(KnowledgeConnection, connection_id)
        assert json.loads(connection.config)["integration_revision"] == 1
        assert not source_enabled(db, connection)


@pytest.fixture
def files_api(setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hub.auth import token_hash
    from hub.db import LoginSession
    from hub.google_drive_files import install_google_drive_files
    from hub.knowledge_connections import install_knowledge_connections

    factory, cfg, identifier, connection_id, body = setup
    app = FastAPI()
    app.state.settings, app.state.sessions, app.state.tasks = cfg, factory, set()
    install_google_drive_files(app, cfg, factory)
    install_knowledge_connections(app, cfg, factory)
    token, csrf = "synthetic-session-token", "synthetic-csrf"
    with factory() as db:
        db.add(LoginSession(token_hash=token_hash(token), csrf=csrf, expires=time.time() + 3600))
        db.get(KnowledgeConnection, connection_id).status = "needs_setup"
        db.commit()
    with TestClient(app) as client:
        client.cookies.set("hub_session", token)
        yield client, {"Origin": cfg.origin, "X-CSRF-Token": csrf}, setup


def test_native_source_api_uses_existing_knowledge_project_and_rejects_generic_crafting(
    files_api, fake
):
    client, headers, values = files_api
    factory, cfg, identifier, old_connection, body = values
    source = client.post(
        f"/api/integrations/google-drive/{identifier}/source",
        headers=headers,
        json={"expected_revision": 1, "folder_id": "source-folder", "max_files": 25},
    )
    assert source.status_code == 200, source.text
    result = source.json()
    assert result["connection_id"] == old_connection
    with factory() as db:
        assert db.get(Project, result["project_id"]).kind == "knowledge"
        assert not db.get(KnowledgeConnection, old_connection).encrypted_secret
    assert (
        client.post("/api/knowledge-sources", headers=headers, json=body.public()).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/knowledge-sources/{old_connection}",
            headers=headers,
            json=body.public() | {"revision": result["revision"]},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/integrations/google-drive/{identifier}/source",
            json={"expected_revision": 1, "folder_id": "source-folder"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/integrations/google-drive/{identifier}/source",
            headers=headers,
            json={"expected_revision": 2, "folder_id": "source-folder"},
        ).status_code
        == 409
    )


def test_actual_artifact_second_read_mismatch_is_rejected_before_any_drive_http(
    real_artifact, fake, monkeypatch
):
    import test_artifact_api
    from hub.google_drive_files import _artifact_bytes

    app, client, headers, cfg, project_id, spec = real_artifact
    rendered = test_artifact_api.create(client, headers, project_id, spec).json()
    rendered = test_artifact_api.pump(app, client, cfg, project_id, rendered)

    class ChangedAfterCheck:
        def read_bytes(self):
            return b"synthetic tamper after validated path"

    monkeypatch.setattr("hub.google_drive_files.output_file", lambda *a: ChangedAfterCheck())
    with app.state.sessions() as db:
        with pytest.raises(ValueError, match="zwischen Prüfung"):
            _artifact_bytes(db, cfg, rendered["artifact_id"], 1)
    assert fake.calls == []


def test_native_source_narrows_approved_root_without_oauth_or_storage_mutation(files_api, fake):
    client, headers, values = files_api
    factory, cfg, identifier, connection_id, _ = values
    with factory() as db:
        profile = db.get(Integration, identifier)
        config = json.loads(profile.config)
        config.update(source_folder_id="root", storage_folder_id="existing-managed-storage")
        profile.config = json.dumps(config)
        before_secret = profile.encrypted_secret
        db.commit()
    fake.stored["selected-child"] = {
        "id": "selected-child",
        "name": "Selected",
        "mimeType": "application/vnd.google-apps.folder",
        "trashed": False,
    }
    response = client.post(
        f"/api/integrations/google-drive/{identifier}/source",
        headers=headers,
        json={"expected_revision": 1, "folder_id": "selected-child"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["config"]["folder"] == "selected-child"
    with factory() as db:
        profile = db.get(Integration, identifier)
        assert profile.revision == 1 and profile.encrypted_secret == before_secret
        assert json.loads(profile.config)["storage_folder_id"] == "existing-managed-storage"
        connection = db.get(KnowledgeConnection, connection_id)
        assert source_enabled(db, connection)
        assert json.loads(connection.config)["integration_revision"] == 1


def test_native_source_cannot_escape_nonroot_scope_before_any_google_request(files_api, fake):
    client, headers, values = files_api
    identifier = values[2]
    response = client.post(
        f"/api/integrations/google-drive/{identifier}/source",
        headers=headers,
        json={"expected_revision": 1, "folder_id": "different-child"},
    )
    assert response.status_code == 409 and fake.calls == []


def test_source_folder_change_retires_old_snapshots_and_new_index_cannot_mix_them(files_api, fake):
    from hub.db import SourceChunk
    from hub.knowledge import context, original, store

    client, headers, values = files_api
    factory, cfg, identifier, connection_id, _ = values
    with factory() as db:
        profile = db.get(Integration, identifier)
        config = json.loads(profile.config)
        config["source_folder_id"] = "root"
        profile.config = json.dumps(config)
        connection = db.get(KnowledgeConnection, connection_id)
        old = Source(
            project_id=connection.project_id,
            name="old-scope.txt",
            status="ready",
            sha256=hashlib.sha256(b"OLD_SCOPE_MARKER").hexdigest(),
            size=16,
        )
        db.add(old)
        db.flush()
        store(cfg, old, b"OLD_SCOPE_MARKER")
        db.add(SourceChunk(source_id=old.id, locator="1", content="OLD_SCOPE_MARKER"))
        db.commit()
        old_id = old.id
    fake.stored["new-folder"] = {"id": "new-folder", "name": "New scope", "mimeType": FOLDER_MIME}
    response = client.post(
        f"/api/integrations/google-drive/{identifier}/source",
        headers=headers,
        json={"expected_revision": 1, "folder_id": "new-folder"},
    )
    assert response.status_code == 200, response.text
    with factory() as db:
        old = db.get(Source, old_id)
        assert old.status == "superseded" and old.revision == 2
        assert original(cfg, old).read_bytes() == b"OLD_SCOPE_MARKER"
        connection = db.get(KnowledgeConnection, connection_id)
        connection.status = "indexing"
        connection.enabled = True
        db.commit()
        revision = connection.revision
    fake.allowed_parent = "new-folder"
    fake.files = [
        {"id": "new-file", "name": "new.txt", "mimeType": "text/plain", "parents": ["new-folder"]}
    ]
    asyncio.run(index_connection(factory, cfg, connection_id, revision))
    with factory() as db:
        connection = db.get(KnowledgeConnection, connection_id)
        active = list(
            db.scalars(
                select(Source).where(
                    Source.project_id == connection.project_id, Source.status == "ready"
                )
            )
        )
        assert len(active) == 1 and active[0].id != old_id
        selected = context(db, connection.project_id, "DRIVE_SOURCE_SEVEN")
        assert any("DRIVE_SOURCE_SEVEN" in part.content for part in selected)
        assert all("OLD_SCOPE_MARKER" not in part.content for part in selected)
        assert original(cfg, db.get(Source, old_id)).read_bytes() == b"OLD_SCOPE_MARKER"


def test_account_revision_rebinding_retires_same_folder_old_snapshots(files_api, fake):
    from hub.provider_settings import decrypt

    client, headers, values = files_api
    factory, cfg, identifier, connection_id, _ = values
    with factory() as db:
        connection = db.get(KnowledgeConnection, connection_id)
        old = Source(
            project_id=connection.project_id,
            name="old-account.txt",
            sha256="a" * 64,
            size=1,
            status="queued",
        )
        db.add(old)
        db.flush()
        old_id = old.id
        profile = db.get(Integration, identifier)
        data = json.loads(profile.config)
        data["account_email"] = "different@example.invalid"
        private = json.loads(decrypt(cfg, "integration:" + identifier, profile.encrypted_secret))
        private["account_email"] = data["account_email"]
        profile.config = json.dumps(data)
        profile.revision = 2
        profile.encrypted_secret = encrypt(cfg, "integration:" + identifier, json.dumps(private))
        db.commit()
    response = client.post(
        f"/api/integrations/google-drive/{identifier}/source",
        headers=headers,
        json={"expected_revision": 2, "folder_id": "source-folder"},
    )
    assert response.status_code == 200, response.text
    with factory() as db:
        old = db.get(Source, old_id)
        assert old.status == "superseded" and old.revision == 2
        assert (
            json.loads(db.get(KnowledgeConnection, connection_id).config)["integration_revision"]
            == 2
        )


def test_readonly_folder_reconcile_api_confirms_lost_reply_without_second_post(files_api, fake):
    client, headers, values = files_api
    factory, cfg, identifier, _, _ = values
    fake.lose_response = True
    unknown = execute_transfer(
        factory,
        cfg,
        identifier,
        DriveFolderInput(expected_revision=1, request_id=uuid.uuid4()),
        "folder",
    )
    assert unknown["status"] == "uncertain"
    fake.calls.clear()
    generation = fake.generation
    endpoint = f"/api/integrations/google-drive/{identifier}/exports/{unknown['id']}/reconcile"
    assert client.post(endpoint, json={"expected_revision": 1}).status_code == 403
    result = client.post(endpoint, headers=headers, json={"expected_revision": 1})
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded" and result.json()["integration_revision"] == 2
    assert fake.calls == [("GET", unknown["remote_id"])] and fake.generation == generation


def test_readonly_export_reconcile_uses_stored_receipt_even_when_local_artifact_unavailable(
    setup, fake, monkeypatch
):
    from hub.google_drive_files import reconcile_transfer

    factory, cfg, identifier, _, _ = setup
    folder = execute_transfer(
        factory,
        cfg,
        identifier,
        DriveFolderInput(expected_revision=1, request_id=uuid.uuid4()),
        "folder",
    )
    assert folder["status"] == "succeeded"
    monkeypatch.setattr(
        "hub.google_drive_files._artifact_bytes",
        lambda *args: (b"frozen original bytes", "Frozen.pdf", "application/pdf"),
    )
    fake.lose_response = True
    unknown = execute_transfer(
        factory,
        cfg,
        identifier,
        DriveExportInput(
            expected_revision=2,
            request_id=uuid.uuid4(),
            artifact_id=uuid.uuid4(),
            artifact_revision=1,
            cloud_upload_approved=True,
        ),
        "export",
    )
    assert unknown["status"] == "uncertain"

    def unavailable(*args):
        pytest.fail("Read-only reconciliation must not read or re-upload private artifact bytes")

    monkeypatch.setattr("hub.google_drive_files._artifact_bytes", unavailable)
    fake.calls.clear()
    generation = fake.generation
    result = reconcile_transfer(factory, cfg, identifier, unknown["id"], 2)
    assert result["status"] == "succeeded"
    assert fake.calls == [("GET", unknown["remote_id"])] and fake.generation == generation


def test_reconcile_revoked_authority_keeps_uncertain_receipt_unchanged(setup, fake):
    from hub.google_drive_files import reconcile_transfer

    factory, cfg, identifier, _, _ = setup
    fake.lose_response = True
    unknown = execute_transfer(
        factory,
        cfg,
        identifier,
        DriveFolderInput(expected_revision=1, request_id=uuid.uuid4()),
        "folder",
    )
    with factory() as db:
        row = db.get(GoogleDriveTransfer, unknown["id"])
        before = (row.status, row.error, row.updated)
        db.get(Integration, identifier).enabled = False
        db.commit()
    fake.calls.clear()
    result = reconcile_transfer(factory, cfg, identifier, unknown["id"], 1)
    assert result["status"] == "uncertain" and fake.calls == []
    with factory() as db:
        row = db.get(GoogleDriveTransfer, unknown["id"])
        assert (row.status, row.error, row.updated) == before


@pytest.mark.parametrize("entrypoint", ["execute", "reconcile"])
def test_competing_folder_success_and_profile_revision_change_cannot_downgrade_receipt(
    setup, fake, entrypoint
):
    from hub.google_drive_files import reconcile_transfer

    factory, cfg, identifier, _, _ = setup
    body = DriveFolderInput(expected_revision=1, request_id=uuid.uuid4())
    fake.lose_response = True
    unknown = execute_transfer(factory, cfg, identifier, body, "folder")
    assert unknown["status"] == "uncertain"
    original = fake.metadata

    def winner(self, file_id):
        metadata = original(self, file_id)
        # Another verifier wins after this reader's HTTP, before its final guard.
        with factory() as db:
            row = db.get(GoogleDriveTransfer, unknown["id"])
            row.status = "succeeded"
            row.error = ""
            profile = db.get(Integration, identifier)
            config = json.loads(profile.config)
            config["storage_folder_id"] = file_id
            profile.config = json.dumps(config)
            profile.revision = 2
            db.commit()
        return metadata

    fake.metadata = winner
    try:
        if entrypoint == "execute":
            result = execute_transfer(factory, cfg, identifier, body, "folder")
        else:
            result = reconcile_transfer(factory, cfg, identifier, unknown["id"], 1)
        assert result["status"] == "succeeded" and result["integration_revision"] == 2
        with factory() as db:
            assert db.get(GoogleDriveTransfer, unknown["id"]).status == "succeeded"
    finally:
        fake.metadata = original


def test_drive_source_scope_is_rechecked_under_owner_lock_before_snapshot_persistence(
    setup, fake, monkeypatch
):
    import hub.knowledge_connections as module

    factory, cfg, identifier, connection_id, _ = setup
    with factory() as db:
        profile = db.get(Integration, identifier)
        config = json.loads(profile.config)
        config["source_folder_id"] = "root"
        profile.config = json.dumps(config)
        db.commit()
    real_owner, real_task = module.ownership_lock, module.lock
    order = []

    def owner_gate(db):
        order.append("owner")
        if len(order) == 1:
            # A human scope change has committed after download/guard but before
            # this persist transaction gets the shared ownership lock.
            with factory() as other:
                connection = other.get(KnowledgeConnection, connection_id)
                config = json.loads(connection.config)
                config["folder"] = "new-scope"
                connection.config = json.dumps(config)
                connection.revision += 1
                connection.status = "needs_setup"
                other.commit()
        real_owner(db)

    def task_gate(db):
        order.append("task")
        real_task(db)

    monkeypatch.setattr(module, "ownership_lock", owner_gate)
    monkeypatch.setattr(module, "lock", task_gate)
    asyncio.run(index_connection(factory, cfg, connection_id, 1))
    assert order[:2] == ["owner", "task"]
    with factory() as db:
        assert not list(db.scalars(select(Source)))
        connection = db.get(KnowledgeConnection, connection_id)
        assert connection.revision == 2 and connection.status == "needs_setup"
        assert json.loads(connection.config)["folder"] == "new-scope"
