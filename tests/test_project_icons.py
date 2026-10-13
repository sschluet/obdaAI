"""Project icon metadata is curated, persistent and compatible with old editors."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from hub.project_icons import PROJECT_ICONS
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

pytest_plugins = ["test_knowledge"]


def test_project_icons_catalog_requires_login(knowledge):
    app, client, headers, cfg, vault = knowledge
    assert client.get("/api/project-icons").json() == list(PROJECT_ICONS)
    assert len(set(PROJECT_ICONS)) == 32
    client.cookies.clear()
    assert client.get("/api/project-icons").status_code == 401


def test_project_icon_persists_without_old_edit_reset(knowledge):
    app, client, headers, cfg, vault = knowledge
    created = client.post("/api/projects", json={"name": "Synthetic icon"}, headers=headers).json()
    pid = created["id"]
    assert created["icon"] == "folder"
    updated = client.patch(
        f"/api/projects/{pid}",
        json={"name": created["name"], "revision": 1, "icon": "rocket"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["icon"] == "rocket"
    # Existing clients may edit/archive without knowing this new field.
    for revision, extra in [(2, {}), (3, {"icon": None})]:
        saved = client.patch(
            f"/api/projects/{pid}",
            json={"name": created["name"], "revision": revision, "archived": True, **extra},
            headers=headers,
        )
        assert saved.status_code == 200
        assert saved.json()["icon"] == "rocket"
    assert client.get(f"/api/projects/{pid}").json()["icon"] == "rocket"
    assert next(p for p in client.get("/api/projects").json() if p["id"] == pid)["icon"] == "rocket"
    stale = client.patch(
        f"/api/projects/{pid}",
        json={"name": created["name"], "revision": 1, "icon": "heart"},
        headers=headers,
    )
    assert stale.status_code == 409
    assert client.get(f"/api/projects/{pid}").json()["icon"] == "rocket"


def test_all_curated_icons_create(knowledge):
    app, client, headers, cfg, vault = knowledge
    for icon in PROJECT_ICONS:
        response = client.post(
            "/api/projects", json={"name": "Synthetic", "icon": icon}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["icon"] == icon


@pytest.mark.parametrize(
    "icon",
    [
        "https://example.com/logo.svg",
        "<svg onload=alert(1) />",
        "../logo",
        "unknown",
        "",
        12,
        {"svg": "x"},
    ],
)
def test_uncurated_icons_rejected_on_create_and_edit(knowledge, icon):
    app, client, headers, cfg, vault = knowledge
    project = client.post(
        "/api/projects", json={"name": "Synthetic", "icon": "heart"}, headers=headers
    ).json()
    assert (
        client.post(
            "/api/projects", json={"name": "Synthetic", "icon": icon}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/projects/{project['id']}",
            json={"name": "Synthetic", "revision": 1, "icon": icon},
            headers=headers,
        ).status_code
        == 422
    )
    current = client.get(f"/api/projects/{project['id']}").json()
    assert current["revision"] == 1 and current["icon"] == "heart"


def test_migration_preserves_existing_projects_and_default(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "migration.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "0032")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO projects "
                "(id, name, description, instructions, label, revision, archived, kind) "
                "VALUES ('existing', 'Synthetic existing', 'kept', 'kept instruction', "
                "'LOCAL_ONLY', 7, false, 'project')"
            )
        )
    command.upgrade(config, "0033")
    with engine.connect() as db:
        existing = db.execute(
            text(
                "SELECT name, description, instructions, label, revision, archived, icon "
                "FROM projects WHERE id='existing'"
            )
        ).one()
        assert tuple(existing) == (
            "Synthetic existing",
            "kept",
            "kept instruction",
            "LOCAL_ONLY",
            7,
            False,
            "folder",
        )
    command.downgrade(config, "0032")
    assert "icon" not in {c["name"] for c in inspect(engine).get_columns("projects")}
    with engine.connect() as db:
        assert (
            db.scalar(text("SELECT name FROM projects WHERE id='existing'")) == "Synthetic existing"
        )
    command.upgrade(config, "0033")
    with engine.connect() as db:
        assert db.scalar(text("SELECT icon FROM projects WHERE id='existing'")) == "folder"


@pytest.mark.skipif(
    not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PostgreSQL required"
)
def test_project_icon_migration_postgres(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci allowed")
    engine = create_engine(url)
    schema = "projecticons_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text("CREATE TABLE projects (id varchar(36) PRIMARY KEY, name text NOT NULL)")
            )
            connection.execute(
                text("INSERT INTO projects VALUES ('existing', 'Synthetic existing')")
            )
            spec = importlib.util.spec_from_file_location(
                "project_icon_migration", Path("migrations/versions/0033_project_icons.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
            module.upgrade()
            assert connection.scalar(text("SELECT icon FROM projects")) == "folder"
            connection.execute(
                text("INSERT INTO projects (id, name) VALUES ('future', 'Synthetic future')")
            )
            assert (
                connection.scalar(text("SELECT icon FROM projects WHERE id='future'")) == "folder"
            )
            connection.execute(text("UPDATE projects SET icon='rocket' WHERE id='existing'"))
            module.downgrade()
            assert (
                connection.scalar(text("SELECT name FROM projects WHERE id='existing'"))
                == "Synthetic existing"
            )
            assert "icon" not in {c["name"] for c in inspect(connection).get_columns("projects")}
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
