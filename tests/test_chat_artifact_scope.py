"""Conversation artifacts have exact scope, private drafts and durable deletion."""

import asyncio
import uuid

import pytest
import test_artifact_api
import test_artifact_drafts
from hub.artifact_api import CreateArtifact, artifact_service
from hub.artifact_drafts import DraftInput, preview
from hub.artifact_scope import owner
from hub.db import Artifact, ArtifactRevision, Conversation, Project
from hub.deletion import DeletionInput, permanently_delete
from hub.deletion import preview as deletion_preview
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from test_artifact_api.setup.__wrapped__(tmp_path, monkeypatch)


def chat(app, **fields):
    with app.state.sessions() as db:
        row = Conversation(**fields)
        db.add(row)
        db.commit()
        return row.id


def spec():
    return {
        "plan": {
            "kind": "docx",
            "title": "Private Datei",
            "sections": [{"heading": "Text", "paragraphs": ["Synthetischer Inhalt"]}],
        }
    }


def test_chat_create_replay_scope_listing_and_cancel(setup):
    app, c, h, cfg, pid, _ = setup
    first, other = chat(app), chat(app)
    body = {"request_id": str(uuid.uuid4()), "spec": spec()}
    prefix = f"/api/conversations/{first}/artifacts"
    response = c.post(prefix, json=body, headers=h)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["project_id"] is None and result["conversation_id"] == first
    assert c.post(prefix, json=body, headers=h).json()["artifact_id"] == result["artifact_id"]
    assert c.post(f"/api/conversations/{other}/artifacts", json=body, headers=h).status_code == 409
    assert c.get(f"/api/conversations/{other}/artifacts").json() == []
    assert c.get(f"/api/projects/{pid}/artifacts").json() == []
    aid = result["artifact_id"]
    path = f"{prefix}/{aid}/versions/1"
    assert c.get(path.replace(first, other) + "/download").status_code == 404
    assert c.get(f"/api/projects/{pid}/artifacts/{aid}/versions/1/preview/1").status_code == 404
    assert c.post(path + "/cancel", headers=h).json()["status"] == "cancelled"
    assert len(c.get(prefix).json()) == 1


@pytest.mark.parametrize(
    "fields", [{"archived": True}, {"memory_scope": "global"}, {"purpose": "use_case"}]
)
def test_chat_invalid_owner_never_creates_or_reads(setup, fields):
    app, c, h, cfg, pid, _ = setup
    cid = chat(app, **fields)
    prefix = f"/api/conversations/{cid}/artifacts"
    assert (
        c.post(
            prefix, headers=h, json={"request_id": str(uuid.uuid4()), "spec": spec()}
        ).status_code
        == 404
    )
    assert c.get(prefix).status_code == 404


def test_project_chat_cannot_hide_project_scope_and_sources(setup):
    app, c, h, cfg, pid, source_spec = setup
    linked = chat(app, project_id=pid)
    free = chat(app)
    assert c.get(f"/api/conversations/{linked}/artifacts").status_code == 404
    assert (
        c.post(
            f"/api/conversations/{free}/artifacts",
            headers=h,
            json={"request_id": str(uuid.uuid4()), "spec": source_spec},
        ).status_code
        == 409
    )
    with app.state.sessions() as db:
        with pytest.raises(ValueError):
            owner(db, None)
        with pytest.raises(ValueError):
            owner(db, pid, free)


def test_chat_draft_exact_scope_local_metadata_and_archive_race(setup):
    app, c, h, cfg, pid, _ = setup
    cid, other = chat(app), chat(app)
    provider = test_artifact_drafts.DraftProvider(test_artifact_drafts.DOCUMENT)
    proposal = asyncio.run(
        preview(
            app.state.sessions,
            cfg,
            None,
            DraftInput(goal="Erstelle einen Bericht", kind="docx"),
            provider,
            conversation_id=cid,
        )
    )
    assert provider.calls == 1
    body = {
        "request_id": str(uuid.uuid4()),
        "spec": proposal["spec"],
        "draft_token": proposal["draft_token"],
    }
    assert c.post(f"/api/conversations/{other}/artifacts", json=body, headers=h).status_code == 409
    assert c.post(f"/api/projects/{pid}/artifacts", json=body, headers=h).status_code == 409
    result = c.post(f"/api/conversations/{cid}/artifacts", json=body, headers=h)
    assert result.status_code == 200, result.text
    assert result.json()["draft"]["conversation_id"] == cid
    with app.state.sessions() as db:
        db.get(Conversation, cid).archived = True
        db.commit()
    assert c.post(f"/api/conversations/{cid}/artifacts", json=body, headers=h).status_code == 404


def test_chat_delete_blocks_active_artifacts_then_deletes_only_owned(setup):
    app, c, h, cfg, pid, _ = setup
    cid, other = chat(app), chat(app)
    with app.state.sessions() as db:
        own = Artifact(conversation_id=cid)
        sibling = Artifact(conversation_id=other)
        project = Artifact(project_id=pid)
        db.add_all([own, sibling, project])
        db.flush()
        row = ArtifactRevision(
            artifact_id=own.id,
            revision=1,
            request_key=str(uuid.uuid4()),
            spec='{"plan":{"kind":"docx","title":"Text","sections":[{"heading":"Text"}]}}',
            spec_sha256="a" * 64,
            status="rendering",
        )
        db.add(row)
        db.commit()
        preview = deletion_preview(db, "conversation", cid, cfg)
        assert preview["counts"]["artifacts"] == 1 and preview["blockers"]
        row.status = "cancelled"
        db.commit()
        preview = deletion_preview(db, "conversation", cid, cfg)
        result = permanently_delete(
            db, cfg, "conversation", cid, DeletionInput(expected_state=preview["expected_state"])
        )
        assert result["ok"]
        assert db.get(Conversation, cid) is None
        assert db.get(Artifact, own.id) is None
        assert db.get(ArtifactRevision, (own.id, 1)) is None
        assert db.get(Artifact, sibling.id) and db.get(Artifact, project.id)
        assert db.get(Project, pid)


def test_artifact_db_scope_constraint(setup):
    app, c, h, cfg, pid, _ = setup
    cid = chat(app)
    for fields in [{}, {"project_id": pid, "conversation_id": cid}]:
        with app.state.sessions() as db:
            db.add(Artifact(**fields))
            with pytest.raises(IntegrityError):
                db.commit()


def test_service_missing_owner_and_both_scopes_are_rejected(setup):
    app, c, h, cfg, pid, _ = setup
    cid = chat(app)
    service = artifact_service(cfg, app.state.sessions)
    body = CreateArtifact.model_validate({"request_id": str(uuid.uuid4()), "spec": spec()})
    for project_id, conversation_id in [(None, None), (pid, cid)]:
        with pytest.raises(Exception) as error:
            asyncio.run(service(project_id, None, body, conversation_id=conversation_id))
        assert error.value.status_code == 404
    with app.state.sessions() as db:
        assert not list(db.scalars(select(Artifact)))


def test_chat_preview_accept_download_immutable_revision_and_private_headers(setup):
    # Synthetic preview fixture tests scope/review; Linux Office smoke is separate.
    import hashlib
    import json
    import time
    from pathlib import Path

    from hub.artifact_render import render
    from hub.artifact_specs import ArtifactSpec
    from PIL import Image

    app, c, h, cfg, pid, _ = setup
    cid, other = chat(app), chat(app)
    prefix = f"/api/conversations/{cid}/artifacts"
    result = c.post(
        prefix, headers=h, json={"request_id": str(uuid.uuid4()), "spec": spec()}
    ).json()
    name = result["artifact_id"] + "-1"
    request = Path(cfg.artifact_request_dir) / name
    for _ in range(120):
        if request.exists():
            break
        time.sleep(0.025)
    assert request.exists()
    output = Path(cfg.artifact_result_dir) / name
    output.mkdir()
    manifest = render(ArtifactSpec.model_validate(spec()), [], output / "version")
    image = output / "version" / "previews" / "page-1.png"
    image.parent.mkdir()
    Image.new("RGB", (100, 100), "white").save(image)
    manifest.update(
        spec_sha256=result["spec_sha256"],
        status="needs_review",
        previews=[
            {
                "page": 1,
                "filename": "previews/page-1.png",
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "bytes": image.stat().st_size,
            }
        ],
    )
    (output / "manifest.json").write_text(json.dumps(manifest))
    row = c.get(prefix).json()[0]
    assert row["status"] == "needs_review"
    path = f"{prefix}/{row['artifact_id']}/versions/1"
    preview_file = c.get(path + "/preview/1")
    assert preview_file.status_code == 200 and preview_file.headers["cache-control"] == "no-store"
    assert c.get(path.replace(cid, other) + "/preview/1").status_code == 404
    assert c.get(path + "/download").status_code == 409
    assert (
        c.post(
            path + "/accept", headers=h, json=test_artifact_api.acceptance(row, False)
        ).status_code
        == 409
    )
    assert (
        c.post(path + "/accept", headers=h, json=test_artifact_api.acceptance(row)).json()["status"]
        == "published"
    )
    downloaded = c.get(path + "/download")
    assert (
        downloaded.status_code == 200
        and downloaded.content == (output / "version" / "artifact.docx").read_bytes()
    )
    assert downloaded.headers["cache-control"] == "no-store"
    assert c.get(path.replace(cid, other) + "/download").status_code == 404
    revision = c.post(
        f"{prefix}/{row['artifact_id']}/versions",
        headers=h,
        json={"request_id": str(uuid.uuid4()), "expected_revision": 1, "spec": spec()},
    )
    assert revision.status_code == 200 and revision.json()["revision"] == 2
    assert c.get(path + "/download").content == downloaded.content
    assert c.post(path + "/cancel", headers=h).status_code == 409


def test_chat_selected_answer_and_research_require_exact_conversation(setup):
    import json
    import time

    from hub.artifact_chat import ChatSource
    from hub.artifact_chat import binding as answer_binding
    from hub.artifact_research import binding as research_binding
    from hub.artifact_research import verify as research_verify
    from hub.db import Message, Research, Run

    app, c, h, cfg, pid, _ = setup
    cid, other = chat(app), chat(app)
    with app.state.sessions() as db:
        message = Message(conversation_id=cid, role="assistant", content="Synthetische Antwort")
        run = Run(
            conversation_id=cid,
            status="succeeded",
            context_snapshot=json.dumps({"web_search_allowed": True, "web_query": "synthetic"}),
        )
        db.add_all([message, run])
        db.flush()
        research = Research(
            id=run.id,
            project_id=None,
            query="synthetic",
            results=json.dumps(
                [
                    {
                        "url": "https://example.org/evidence",
                        "title": "Synthetic",
                        "content": "Public data",
                        "retrieved_at": time.time(),
                    }
                ]
            ),
        )
        db.add(research)
        db.commit()
        selected = ChatSource(conversation_id=cid, message_id=message.id, revision=1)
        _, answer_receipt = answer_binding(db, None, selected, conversation_id=cid)
        assert answer_receipt["conversation_id"] == cid
        _, receipt = research_binding(db, run.id, None, "synthetic", conversation_id=cid)
        assert receipt["conversation_id"] == cid
        research_verify(db, receipt, None, conversation_id=cid)
        for scope in [None, other]:
            with pytest.raises(ValueError):
                answer_binding(db, None, selected, conversation_id=scope)
            with pytest.raises(ValueError):
                research_binding(db, run.id, None, "synthetic", conversation_id=scope)


def test_archived_chat_worker_finishes_failed_without_creating_spool(setup):
    from pathlib import Path

    from hub.artifact_runner import canonical
    from hub.artifact_specs import ArtifactSpec
    from hub.artifacts import digest, execute_artifact

    app, c, h, cfg, pid, _ = setup
    cid = chat(app, archived=True)
    with app.state.sessions() as db:
        artifact = Artifact(conversation_id=cid)
        db.add(artifact)
        db.flush()
        document = canonical(ArtifactSpec.model_validate(spec()))
        row = ArtifactRevision(
            artifact_id=artifact.id,
            revision=1,
            request_key=str(uuid.uuid4()),
            spec=document,
            spec_sha256=digest(document),
            status="queued",
        )
        db.add(row)
        db.commit()
        aid = artifact.id
    asyncio.run(execute_artifact(app.state.sessions, cfg, aid, 1))
    with app.state.sessions() as db:
        assert db.get(ArtifactRevision, (aid, 1)).status == "failed"
    assert not (Path(cfg.artifact_request_dir) / (aid + "-1")).exists()
