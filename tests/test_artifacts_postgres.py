"""Real PG commit/rollback and duplicate delivery across the artifact file boundary."""

import asyncio
import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from hub.artifact_preview import previews
from hub.artifact_render import render
from hub.artifact_runner import canonical
from hub.artifact_specs import ArtifactSpec
from hub.artifacts import digest
from hub.config import Settings
from hub.db import Artifact, ArtifactRevision, Project, Source, session_factory
from hub.jobs import enqueue_artifact, worker_app
from hub.knowledge import store
from PIL import Image
from sqlalchemy import delete, text


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG fixture required")
def test_artifact_commit_rollback_and_duplicate_workers(tmp_path, monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    if "127.0.0.1" not in url or not url.endswith("/hub_ci"):
        pytest.fail("Only loopback hub_ci is allowed")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    requests, results = tmp_path / "requests", tmp_path / "results"
    requests.mkdir()
    results.mkdir()
    cfg = Settings(
        database_url=url,
        source_dir=str(tmp_path / "sources"),
        artifact_request_dir=str(requests),
        artifact_result_dir=str(results),
    )
    factory = session_factory(url)
    image = tmp_path / "synthetic.png"
    Image.new("RGB", (128, 128), "#153976").save(image)
    content = image.read_bytes()
    with factory() as db:
        project = Project(name="Synthetic PG artifact")
        db.add(project)
        db.flush()
        source = Source(
            project_id=project.id,
            name="synthetic.png",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            status="ready",
        )
        db.add(source)
        db.flush()
        store(cfg, source, content)
        spec = ArtifactSpec.model_validate(
            {
                "sources": [
                    {"id": source.id, "revision": source.revision, "sha256": source.sha256}
                ],
                "plan": {
                    "kind": "image",
                    "title": "Synthetic queued image",
                    "tiles": [{"source": 0}],
                    "tile_width": 128,
                    "tile_height": 128,
                },
            }
        )
        artifact = Artifact(project_id=project.id)
        db.add(artifact)
        db.commit()
        aid, pid, sid = artifact.id, project.id, source.id
    document = canonical(spec)
    try:
        with factory() as db:
            row = ArtifactRevision(
                artifact_id=aid,
                revision=1,
                request_key=str(uuid.uuid4()),
                spec=document,
                spec_sha256=digest(document),
            )
            db.add(row)
            db.flush()
            enqueue_artifact(db, cfg, aid, 1)
            db.rollback()
            assert db.get(ArtifactRevision, (aid, 1)) is None
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM hub_queue.procrastinate_jobs "
                        "WHERE task_name='hub.artifact' AND args->>'artifact_id'=:aid"
                    ),
                    {"aid": aid},
                )
                == 0
            )
            row = ArtifactRevision(
                artifact_id=aid,
                revision=1,
                request_key=str(uuid.uuid4()),
                spec=document,
                spec_sha256=digest(document),
            )
            db.add(row)
            db.flush()
            enqueue_artifact(db, cfg, aid, 1)
            enqueue_artifact(db, cfg, aid, 1)
            db.commit()
        queue = worker_app(cfg, include_maintenance=False)

        async def local_file_boundary():
            request = requests / (aid + "-1")
            for _ in range(200):
                if request.exists():
                    break
                await asyncio.sleep(0.025)
            assert request.exists()
            assert (request / "source-0").read_bytes() == content
            output = results / request.name
            output.mkdir()
            manifest = render(spec, [request / "source-0"], output / "version")
            manifest.update(
                spec_sha256=digest(document),
                status="needs_review",
                previews=previews(output / "version" / manifest["filename"]),
            )
            (output / "manifest.json").write_text(json.dumps(manifest))

        async def work():
            async with queue.open_async():
                await asyncio.gather(
                    local_file_boundary(),
                    queue.run_worker_async(
                        queues=["artifacts"],
                        wait=False,
                        install_signal_handlers=False,
                        concurrency=2,
                    ),
                )

        asyncio.run(work())
        with factory() as db:
            row = db.get(ArtifactRevision, (aid, 1))
            assert row.status == "needs_review" and row.accepted is None
            assert (
                json.loads(row.manifest)["sha256"]
                == hashlib.sha256(
                    (results / (aid + "-1") / "version/artifact.png").read_bytes()
                ).hexdigest()
            )
        assert len(list(requests.iterdir())) == len(list(results.iterdir())) == 1
        assert (Path(cfg.source_dir) / sid / spec.sources[0].sha256).is_file()
    finally:
        with factory() as db:
            db.execute(text("SET LOCAL search_path TO hub_queue, public"))
            db.execute(
                text(
                    "DELETE FROM hub_queue.procrastinate_jobs "
                    "WHERE task_name='hub.artifact' AND args->>'artifact_id'=:aid"
                ),
                {"aid": aid},
            )
            db.execute(delete(ArtifactRevision).where(ArtifactRevision.artifact_id == aid))
            db.execute(delete(Artifact).where(Artifact.id == aid))
            db.execute(delete(Source).where(Source.id == sid))
            db.execute(delete(Project).where(Project.id == pid))
            db.commit()
