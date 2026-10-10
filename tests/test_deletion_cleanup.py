"""Real fixed-path deletion handshakes, restart and filesystem boundaries."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from hub.config import Settings
from hub.db import Base, DeletionCleanup, session_factory
from hub.deletion_cleanup import (
    blocked,
    canonical,
    checked_item,
    consume_markers,
    marker_name,
    process_pending,
    publish,
    receipt_name,
)


@pytest.fixture
def cleanup(tmp_path):
    cfg = Settings(
        database_url="sqlite:///" + str(tmp_path / "db.sqlite"),
        source_dir=str(tmp_path / "sources"),
        parser_result_dir=str(tmp_path / "parsed"),
        artifact_request_dir=str(tmp_path / "requests"),
        artifact_result_dir=str(tmp_path / "results"),
    )
    for name in (
        cfg.source_dir,
        cfg.parser_result_dir,
        cfg.artifact_request_dir,
        cfg.artifact_result_dir,
    ):
        Path(name).mkdir()
    factory = session_factory(cfg.database_url)
    Base.metadata.create_all(factory.kw["bind"])
    ident, source, artifact = (str(uuid4()) for _ in range(3))
    items = [
        {"cleanup_id": ident, "kind": "source", "id": source, "revisions": [1, 2]},
        {"cleanup_id": ident, "kind": "artifact", "id": artifact, "revision": 3},
    ]
    with factory() as db:
        db.add(
            DeletionCleanup(
                id=ident, manifest=canonical(items), source_done=False, artifact_done=False
            )
        )
        db.commit()
    for name in (
        Path(cfg.source_dir) / source,
        Path(cfg.artifact_request_dir) / (artifact + "-3"),
        Path(cfg.artifact_result_dir) / (artifact + "-3"),
    ):
        name.mkdir()
        (name / "data").write_text("private synthetic content")
    (Path(cfg.parser_result_dir) / (source + "-1.json")).write_text("private parsed content")
    return factory, cfg, ident, items


def test_role_handshake_waits_for_real_ack_and_replays_after_restart(cleanup):
    factory, cfg, ident, items = cleanup
    process_pending(factory, cfg, "source")
    assert (Path(cfg.source_dir) / items[0]["id"]).exists()
    assert blocked(Path(cfg.source_dir), "source", items[0]["id"])
    with factory() as db:
        assert not db.get(DeletionCleanup, ident).source_done
    consume_markers(Path(cfg.source_dir), Path(cfg.parser_result_dir), "source")
    assert not (Path(cfg.parser_result_dir) / (items[0]["id"] + "-1.json")).exists()
    # Simulate worker restart: fresh database session resumes from durable receipt.
    process_pending(factory, cfg, "source")
    assert not (Path(cfg.source_dir) / items[0]["id"]).exists()
    process_pending(factory, cfg, "artifact")
    consume_markers(Path(cfg.artifact_request_dir), Path(cfg.artifact_result_dir), "artifact")
    process_pending(factory, cfg, "artifact")
    with factory() as db:
        row = db.get(DeletionCleanup, ident)
        assert row.status == "completed" and row.source_done and row.artifact_done
    assert not (Path(cfg.artifact_result_dir) / (items[1]["id"] + "-3")).exists()
    consume_markers(Path(cfg.source_dir), Path(cfg.parser_result_dir), "source")
    process_pending(factory, cfg, "source")


def test_receipt_spoof_and_symlink_never_acknowledge(cleanup, tmp_path):
    factory, cfg, ident, items = cleanup
    process_pending(factory, cfg, "source")
    outside = tmp_path / "external"
    outside.write_text("preserved")
    (Path(cfg.parser_result_dir) / (items[0]["id"] + "-2.json")).symlink_to(outside)
    with pytest.raises(ValueError):
        consume_markers(Path(cfg.source_dir), Path(cfg.parser_result_dir), "source")
    proof = Path(cfg.parser_result_dir) / ".deletion-cleanup" / receipt_name(items[0])
    assert not proof.exists() and outside.read_text() == "preserved"
    publish(
        Path(cfg.parser_result_dir), receipt_name(items[0]), {"sha256": "0" * 64, "complete": True}
    )
    process_pending(factory, cfg, "source")
    with factory() as db:
        row = db.get(DeletionCleanup, ident)
        assert row.error and not row.source_done and row.status == "pending"
    assert (Path(cfg.source_dir) / items[0]["id"]).exists()


@pytest.mark.parametrize(
    "bad",
    [{"id": "../../external"}, {"revisions": [True]}, {"revisions": [0]}, {"path": "/external"}],
)
def test_manifest_rejects_user_paths_and_invalid_revisions(cleanup, bad):
    item = {**cleanup[3][0], **bad}
    with pytest.raises((ValueError, TypeError)):
        checked_item(item)


def test_source_tombstone_stops_result_recreation(cleanup):
    from hub.source_runner import process

    factory, cfg, ident, items = cleanup
    process_pending(factory, cfg, "source")
    inbox = Path(cfg.source_dir) / "inbox"
    inbox.mkdir()
    source = items[0]["id"]
    job = inbox / (source + ".json")
    job.write_text(json.dumps({"id": source, "sha256": "b" * 64, "suffix": ".txt", "revision": 2}))
    process(Path(cfg.source_dir), Path(cfg.parser_result_dir), job)
    assert not (Path(cfg.parser_result_dir) / (source + "-2.json")).exists()
    assert (Path(cfg.source_dir) / ".deletion-cleanup" / marker_name(items[0])).exists()


def test_other_role_does_not_hide_failed_cleanup(cleanup, tmp_path):
    factory, cfg, ident, items = cleanup
    external = tmp_path / "outside"
    external.write_text("safe")
    (Path(cfg.source_dir) / items[0]["id"] / "link").symlink_to(external)
    process_pending(factory, cfg, "source", inline=True)
    process_pending(factory, cfg, "artifact", inline=True)
    with factory() as db:
        row = db.get(DeletionCleanup, ident)
        assert row.artifact_done and not row.source_done and row.error
        assert row.status == "pending"
    assert external.read_text() == "safe"


def test_artifact_tombstone_prevents_replayed_render(cleanup):
    from hub.artifact_runner import process

    factory, cfg, ident, items = cleanup
    process_pending(factory, cfg, "artifact")
    request = Path(cfg.artifact_request_dir) / (items[1]["id"] + "-3")
    assert not process(request, Path(cfg.artifact_result_dir))
    assert blocked(Path(cfg.artifact_request_dir), "artifact", items[1]["id"], 3)
