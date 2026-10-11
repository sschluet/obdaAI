"""Display settings persist without affecting the personal model profile."""

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.appearance import AppearanceSettings
from hub.db import Run
from PIL import Image, PngImagePlugin
from sqlalchemy import select

pytest_plugins = ["test_chat"]


def photo(size=(32, 32)):
    image = Image.new("RGB", size, (90, 70, 210))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private_metadata", "synthetic metadata must disappear")
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=metadata)
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def save(client, headers, **changes):
    current = client.get("/api/appearance").json()
    revision = current.pop("revision")
    return client.put(
        "/api/appearance",
        headers=headers,
        json={**current, "expected_revision": revision, **changes},
    )


def test_persistence_cas_metadata_and_independent_profile(setup):
    app, client, headers, _ = setup
    before_profile = client.get("/api/personal-profile").json()
    defaults = client.get("/api/appearance").json()
    assert defaults == dict(
        revision=0,
        app_name="obdaAI",
        display_name="",
        avatar_data_url=None,
        density="compact",
        accent="indigo",
    )
    result = save(
        client,
        headers,
        app_name="  Demo Hub  ",
        display_name="Demo Person",
        accent="rose",
        density="comfortable",
        avatar_data_url=photo(),
    )
    assert result.status_code == 200
    assert result.json()["app_name"] == "Demo Hub"
    assert result.json()["revision"] == 1
    raw = base64.b64decode(result.json()["avatar_data_url"].split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as image:
        assert "private_metadata" not in image.info
    assert save(client, headers, expected_revision=0).status_code == 409
    with app.state.sessions() as db:
        assert db.get(AppearanceSettings, 1).display_name == "Demo Person"
    assert client.get("/api/personal-profile").json() == before_profile
    chat = client.post("/api/conversations", headers=headers, json={}).json()["id"]
    client.post(
        f"/api/conversations/{chat}/messages",
        headers=headers,
        json={"content": "synthetic ordinary request"},
    ).raise_for_status()
    with app.state.sessions() as db:
        snapshot = db.scalar(select(Run)).context_snapshot
        assert "Demo Person" not in snapshot and "Demo Hub" not in snapshot
        assert "avatar_data_url" not in json.dumps(json.loads(snapshot))
    with TestClient(create_app(app.state.settings)) as again:
        assert again.get("/api/appearance").status_code == 401
        again.post(
            "/api/login",
            headers={"Origin": "http://testserver"},
            json={"password": "synthetic-test-password"},
        ).raise_for_status()
        assert again.get("/api/appearance").json() == result.json()
    assert save(client, headers, avatar_data_url=None).json()["avatar_data_url"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"app_name": " "},
        {"app_name": "a" * 49},
        {"display_name": "a" * 81},
        {"display_name": "line\nname"},
        {"density": "huge"},
        {"accent": "red"},
        {"expected_revision": True},
        {"unknown": "value"},
        {"avatar_data_url": "https://example.org/avatar.png"},
        {"avatar_data_url": "data:image/svg+xml;base64,PHN2Zy8+"},
        {"avatar_data_url": "data:image/png;base64," + base64.b64encode(b"not a picture").decode()},
        {"avatar_data_url": photo((513, 2))},
        {"avatar_data_url": "data:image/png;base64," + base64.b64encode(b"a" * 153601).decode()},
    ],
)
def test_strict_input_keeps_previous_preferences(setup, changes):
    _, client, headers, _ = setup
    before = client.get("/api/appearance").json()
    assert save(client, headers, **changes).status_code == 422
    assert client.get("/api/appearance").json() == before


def test_auth_and_csrf(setup):
    app, client, headers, _ = setup
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/appearance").status_code == 401
        assert anonymous.put("/api/appearance", json={"expected_revision": 0}).status_code == 401
    assert save(client, {"Origin": "http://testserver"}, app_name="Demo").status_code == 403
    assert save(client, headers, app_name="Demo").status_code == 200
