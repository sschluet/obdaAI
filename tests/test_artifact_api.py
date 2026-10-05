"""Synthetic file boundary tests; real Linux/Office rendering is a separate smoke."""

import hashlib
import json
import time
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from hub.api import create_app
from hub.artifact_preview import previews
from hub.artifact_render import render
from hub.artifact_specs import ArtifactSpec
from hub.auth import password_hash
from hub.config import Settings
from hub.db import ArtifactRevision, Source
from hub.knowledge import store
from PIL import Image
from sqlalchemy import select


@pytest.fixture
def setup(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "db.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    requests, results = tmp_path / "requests", tmp_path / "results"
    requests.mkdir()
    results.mkdir()
    cfg = Settings(
        database_url=url,
        origin="http://testserver",
        secure_cookie=False,
        password_hash=password_hash("synthetic-artifact-password"),
        source_dir=str(tmp_path / "sources"),
        artifact_request_dir=str(requests),
        artifact_result_dir=str(results),
    )
    app = create_app(cfg)
    with TestClient(app) as c:
        csrf = c.post(
            "/api/login",
            json={"password": "synthetic-artifact-password"},
            headers={"Origin": "http://testserver"},
        ).json()["csrf"]
        h = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
        pid = c.post("/api/projects", json={"name": "Synthetic artifact space"}, headers=h).json()[
            "id"
        ]
        image = tmp_path / "input.png"
        Image.new("RGB", (128, 128), "#153976").save(image)
        content = image.read_bytes()
        with app.state.sessions() as db:
            source = Source(
                project_id=pid,
                name="synthetic.png",
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                status="ready",
            )
            db.add(source)
            db.flush()
            store(cfg, source, content)
            db.commit()
            spec = {
                "sources": [
                    {"id": source.id, "revision": source.revision, "sha256": source.sha256}
                ],
                "plan": {
                    "kind": "image",
                    "title": "Bildversion",
                    "tiles": [{"source": 0}],
                    "tile_width": 128,
                    "tile_height": 128,
                },
            }
        yield app, c, h, cfg, pid, spec


def create(c, h, pid, spec, request=None):
    return c.post(
        "/api/projects/" + pid + "/artifacts",
        headers=h,
        json={"spec": spec, "request_id": request or str(uuid.uuid4())},
    )


def pump(app, c, cfg, pid, row):
    request = Path(cfg.artifact_request_dir) / (row["artifact_id"] + "-" + str(row["revision"]))
    for _ in range(120):
        if request.exists():
            break
        time.sleep(0.025)
    assert request.exists()
    spec = ArtifactSpec.model_validate_json((request / "spec.json").read_text())
    output = Path(cfg.artifact_result_dir) / request.name
    output.mkdir()
    manifest = render(
        spec, [request / ("source-" + str(i)) for i in range(len(spec.sources))], output / "version"
    )
    manifest["spec_sha256"] = row["spec_sha256"]
    manifest["status"] = "needs_review"
    manifest["previews"] = previews(output / "version" / manifest["filename"])
    (output / "manifest.json").write_text(json.dumps(manifest))
    rows = c.get("/api/projects/" + pid + "/artifacts").json()
    return next(
        r
        for r in rows
        if r["artifact_id"] == row["artifact_id"] and r["revision"] == row["revision"]
    )


def base(pid, row):
    return (
        "/api/projects/"
        + pid
        + "/artifacts/"
        + row["artifact_id"]
        + "/versions/"
        + str(row["revision"])
    )


def acceptance(row, reviewed=True):
    return {
        "spec_sha256": row["spec_sha256"],
        "output_sha256": row["output"]["sha256"],
        "reviewed_all_pages": reviewed,
    }


def test_real_file_review_download_replay_and_immutable_versions(setup):
    app, c, h, cfg, pid, spec = setup
    request = str(uuid.uuid4())
    result = create(c, h, pid, spec, request)
    assert result.status_code == 200, result.text
    row = result.json()
    assert create(c, h, pid, spec, request).json()["artifact_id"] == row["artifact_id"]
    assert c.get(base(pid, row) + "/download").status_code == 409
    ready = pump(app, c, cfg, pid, row)
    assert ready["status"] == "needs_review"
    preview = c.get(base(pid, ready) + "/preview/1")
    assert preview.content.startswith(b"\x89PNG") and preview.headers["cache-control"] == "no-store"
    assert (
        c.post(base(pid, ready) + "/accept", headers=h, json=acceptance(ready, False)).status_code
        == 409
    )
    accepted = c.post(base(pid, ready) + "/accept", headers=h, json=acceptance(ready)).json()
    assert accepted["status"] == "published"
    assert (
        c.post(base(pid, ready) + "/accept", headers=h, json=acceptance(ready)).json()["accepted"]
        == accepted["accepted"]
    )
    original = c.get(base(pid, ready) + "/download")
    assert original.status_code == 200
    assert hashlib.sha256(original.content).hexdigest() == ready["output"]["sha256"]
    spec["plan"]["title"] = "Zweite echte Version"
    v2 = c.post(
        "/api/projects/" + pid + "/artifacts/" + ready["artifact_id"] + "/versions",
        headers=h,
        json={"request_id": str(uuid.uuid4()), "spec": spec, "expected_revision": 1},
    ).json()
    assert v2["revision"] == 2 and v2["artifact_id"] == ready["artifact_id"]
    assert (
        c.post(
            "/api/projects/" + pid + "/artifacts/" + ready["artifact_id"] + "/versions",
            headers=h,
            json={"request_id": str(uuid.uuid4()), "spec": spec, "expected_revision": 1},
        ).status_code
        == 409
    )
    assert c.get(base(pid, ready) + "/download").content == original.content
    assert c.post(base(pid, ready) + "/cancel", headers=h).status_code == 409


def test_output_drift_and_stale_sources_prevent_acceptance(setup):
    app, c, h, cfg, pid, spec = setup
    ready = pump(app, c, cfg, pid, create(c, h, pid, spec).json())
    with app.state.sessions() as db:
        source = db.get(Source, spec["sources"][0]["id"])
        source.revision += 1
        db.commit()
    assert (
        c.post(base(pid, ready) + "/accept", headers=h, json=acceptance(ready)).status_code == 409
    )
    path = Path(cfg.artifact_result_dir) / (ready["artifact_id"] + "-1") / "version/artifact.png"
    path.chmod(0o600)
    path.write_bytes(b"corrupted")
    assert c.get(base(pid, ready) + "/preview/1").status_code == 409


def test_scope_auth_csrf_no_model_rights_and_cancel_replay(setup):
    app, c, h, cfg, pid, spec = setup
    other = c.post("/api/projects", headers=h, json={"name": "Other"}).json()["id"]
    assert create(c, h, other, spec).status_code == 409
    assert create(c, {}, pid, spec).status_code == 403
    request = str(uuid.uuid4())
    row = create(c, h, pid, spec, request).json()
    assert c.get(base(other, row) + "/preview/1").status_code == 404
    assert c.post(base(pid, row) + "/cancel", headers=h).json()["status"] == "cancelled"
    assert create(c, h, pid, spec, request).json()["status"] == "cancelled"
    changed = json.loads(json.dumps(spec))
    changed["plan"]["title"] = "Mismatch"
    assert create(c, h, pid, changed, request).status_code == 409
    changed["plan"]["command"] = "never executable"
    assert create(c, h, pid, changed).status_code == 422
    with app.state.sessions() as db:
        assert len(db.scalars(select(ArtifactRevision)).all()) == 1
    c.post("/api/logout", headers=h, json={})
    assert c.get("/api/projects/" + pid + "/artifacts").status_code == 401


def test_incomplete_and_foreign_manifest_cannot_publish(setup):
    app, c, h, cfg, pid, spec = setup
    row = create(c, h, pid, spec).json()
    ready = pump(app, c, cfg, pid, row)
    with app.state.sessions() as db:
        version = db.get(ArtifactRevision, (row["artifact_id"], 1))
        manifest = json.loads(version.manifest)
        manifest["previews"][0]["filename"] = "../../foreign.png"
        version.manifest = json.dumps(manifest)
        db.commit()
    assert (
        c.post(base(pid, ready) + "/accept", headers=h, json=acceptance(ready)).status_code == 409
    )
    assert c.get(base(pid, ready) + "/preview/1").status_code == 409


def test_unconfigured_runner_has_no_hidden_fallback(setup):
    app, c, h, cfg, pid, spec = setup
    assert c.get("/api/artifact-status").json()["configured"]
    Path(cfg.artifact_result_dir).rmdir()
    assert not c.get("/api/artifact-status").json()["configured"]
    assert create(c, h, pid, spec).status_code == 503
    with app.state.sessions() as db:
        assert not db.scalars(select(ArtifactRevision)).all()
