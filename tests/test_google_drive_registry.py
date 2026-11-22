"""Native Drive settings cannot be converted or executed by generic adapters."""

import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hub.auth import require_session
from hub.config import Settings
from hub.db import Base, KnowledgeConnection, Project, session_factory
from hub.google_drive_client import API_BASE
from hub.google_drive_files import GoogleDriveTransfer
from hub.integration_api import install_integration_api
from hub.integrations import Integration


@pytest.fixture
def registry(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Registry settings must not perform Google/network requests")

    monkeypatch.setattr("httpx.Client", forbidden)
    cfg = Settings(database_url="sqlite:///" + str(tmp_path / "drive-registry.sqlite"))
    factory = session_factory(cfg.database_url)
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as db:
        row = Integration(
            name="Synthetic Drive",
            kind="google_drive",
            config=json.dumps({"url": API_BASE, "auth": "oauth", "connected": False}),
            enabled=False,
        )
        db.add(row)
        db.commit()
        identifier = row.id
    app = FastAPI()
    app.dependency_overrides[require_session] = lambda: None
    install_integration_api(app, cfg, factory)
    with TestClient(app) as client:
        yield client, factory, identifier


def test_native_registry_is_optional_and_control_does_not_contact_google(registry):
    client, _, identifier = registry
    result = client.get("/api/integrations").json()
    assert "google_drive" in result["types"]
    row = result["integrations"][0]
    assert row["enabled"] is False and row["availability_reason"] == "disabled"
    assert not row["check_available"] and not row["execution_available"]
    response = client.patch(
        f"/api/integrations/{identifier}/control",
        json={"expected_revision": 1, "enabled": True},
    )
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert response.json()["availability_reason"] == "network_disabled"


def test_generic_check_and_edit_cannot_bypass_native_oauth(registry):
    client, factory, identifier = registry
    assert client.post(
        f"/api/integrations/{identifier}/check", json={"expected_revision": 1}
    ).status_code == 422
    assert client.put(
        f"/api/integrations/{identifier}",
        json={
            "expected_revision": 1,
            "name": "Synthetic changed target",
            "kind": "paperless",
            "url": "https://other.example.test",
            "auth": "api_key",
        },
    ).status_code == 422
    with factory() as db:
        row = db.get(Integration, identifier)
        assert row.kind == "google_drive" and row.revision == 1 and row.last_check is None


@pytest.mark.parametrize("reference", ["source", "transfer"])
def test_delete_preserves_referenced_source_or_transfer_evidence(registry, reference):
    client, factory, identifier = registry
    with factory() as db:
        if reference == "source":
            project = Project(name="Synthetic Drive snapshots", kind="knowledge")
            db.add(project)
            db.flush()
            db.add(
                KnowledgeConnection(
                    name="Synthetic Drive source",
                    kind="google_drive",
                    address="www.googleapis.com",
                    project_id=project.id,
                    config=json.dumps({"integration_id": identifier}),
                )
            )
        else:
            db.add(
                GoogleDriveTransfer(
                    request_id=str(uuid4()),
                    request_digest="0" * 64,
                    integration_id=identifier,
                    profile_revision=1,
                    operation="folder",
                    status="uncertain",
                )
            )
        db.commit()
    response = client.request(
        "DELETE", f"/api/integrations/{identifier}", json={"expected_revision": 1}
    )
    assert response.status_code == 409
    with factory() as db:
        assert db.get(Integration, identifier) is not None
