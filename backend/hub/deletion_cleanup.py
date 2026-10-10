"""Durable, fixed-id cleanup across existing read-only container boundaries."""

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from sqlalchemy import and_, or_, select

from hub.config import Settings
from hub.db import ArtifactRevision, DeletionCleanup, Source

NAMESPACE = ".deletion-cleanup"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def checked_id(value: Any) -> str:
    result = str(uuid.UUID(value))
    if result != value:
        raise ValueError("Invalid cleanup identifier")
    return result


def checked_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Invalid cleanup item")
    checked_id(value["cleanup_id"])
    checked_id(value["id"])
    if value.get("kind") == "source":
        revisions = value.get("revisions")
        if set(value) != {"cleanup_id", "id", "kind", "revisions"} or not isinstance(
            revisions, list
        ):
            raise ValueError("Invalid source cleanup")
        if not 1 <= len(revisions) <= 1000 or any(
            type(r) is not int or not 1 <= r <= 1000 for r in revisions
        ):
            raise ValueError("Invalid source revisions")
    elif value.get("kind") == "artifact":
        if (
            set(value) != {"cleanup_id", "id", "kind", "revision"}
            or type(value.get("revision")) is not int
            or not 1 <= value["revision"] <= 100000
        ):
            raise ValueError("Invalid artifact revision")
    else:
        raise ValueError("Invalid cleanup kind")
    return value


def marker_name(item: dict[str, Any]) -> str:
    return (
        str(item["kind"])
        + "-"
        + str(item["id"])
        + ("-" + str(item["revision"]) if item["kind"] == "artifact" else "")
        + ".json"
    )


def safe_root(root: Path) -> None:
    if not root.is_dir() or root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError("Unsafe cleanup root")


def remove(root: Path, child: str) -> None:
    safe_root(root)
    path = root / child
    if any(p.is_symlink() for p in path.parents):
        raise ValueError("Unsafe cleanup path")
    if not path.exists() and not path.is_symlink():
        return
    entries = [path]
    if path.is_dir():
        for entry in path.rglob("*"):
            entries.append(entry)
            if len(entries) > 30000:
                raise ValueError("Cleanup entry limit")
    if len(entries) > 30000 or any(
        p.is_symlink() or not (p.is_file() or p.is_dir()) for p in entries
    ):
        raise ValueError("Unsafe cleanup contents")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def publish(root: Path, name: str, value: Any) -> None:
    safe_root(root)
    namespace = root / NAMESPACE
    namespace.mkdir(mode=0o700, exist_ok=True)
    safe_root(namespace)
    path = namespace / name
    document = canonical(value)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_text() != document:
            raise ValueError("Changed cleanup marker")
        return
    temporary = namespace / ("." + name + "-" + uuid.uuid4().hex)
    with temporary.open("x") as stream:
        stream.write(document)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_marker(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20000:
        raise ValueError("Unsafe cleanup marker")
    item = checked_item(json.loads(path.read_text()))
    if path.name != marker_name(item):
        raise ValueError("Invalid cleanup marker name")
    return item


def blocked(root: Path, kind: str, identifier: str, revision: int | None = None) -> bool:
    # Existence is sufficient to stop recreation, even for a corrupted tombstone.
    name = kind + "-" + identifier + ("-" + str(revision) if revision is not None else "") + ".json"
    path = root / NAMESPACE / name
    return path.exists() or path.is_symlink()


def receipt_name(item: dict[str, Any]) -> str:
    return str(item["cleanup_id"]) + "-" + marker_name(item)


def receipt(item: dict[str, Any]) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(canonical(item).encode()).hexdigest(), "complete": True}


def consume_markers(requests: Path, results: Path, kind: str) -> None:
    """Offline runner: read existing RO request mount; purge only its RW results."""
    safe_root(requests)
    safe_root(results)
    namespace = requests / NAMESPACE
    if not namespace.exists():
        return
    safe_root(namespace)
    markers = list(namespace.glob(kind + "-*.json"))
    if len(markers) > 10000:
        raise ValueError("Cleanup marker limit")
    unsafe = False
    for path in markers:
        try:
            consume_marker(path, results, kind)
        except (ValueError, OSError, KeyError, TypeError):
            unsafe = True
    if unsafe:
        raise ValueError("One cleanup marker could not be acknowledged")


def consume_marker(path: Path, results: Path, kind: str) -> None:
    item = read_marker(path)
    if item["kind"] != kind:
        raise ValueError("Wrong cleanup role")
    if kind == "source":
        for revision in item["revisions"]:
            name = item["id"] + "-" + str(revision)
            remove(results, name + ".json")
            remove(results, "." + name + ".tmp")
    else:
        name = item["id"] + "-" + str(item["revision"])
        for suffix in (name, "." + name + "-pending", "." + name + "-failure"):
            remove(results, suffix)
    publish(results, receipt_name(item), receipt(item))


def queue_cleanup(db: Any, sources: list[Source], revisions: list[ArtifactRevision]) -> str | None:
    if not sources and not revisions:
        return None
    identifier = str(uuid.uuid4())
    items = [
        checked_item(
            {
                "cleanup_id": identifier,
                "kind": "source",
                "id": s.id,
                "revisions": list(range(1, s.revision + 1)),
            }
        )
        for s in sources
    ]
    items += [
        checked_item(
            {
                "cleanup_id": identifier,
                "kind": "artifact",
                "id": r.artifact_id,
                "revision": r.revision,
            }
        )
        for r in revisions
    ]
    if len(items) > 10000:
        raise ValueError("Cleanup item limit")
    db.add(
        DeletionCleanup(
            id=identifier,
            manifest=canonical(items),
            status="pending",
            source_done=not sources,
            artifact_done=not revisions,
        )
    )
    db.flush()
    return identifier


def process_pending(factory: Any, cfg: Settings, role: str, *, inline: bool = False) -> None:
    """RW owner waits for bounded proof from its offline runner before removing inputs."""
    with factory() as db:
        jobs = list(
            db.scalars(
                select(DeletionCleanup)
                .where(
                    DeletionCleanup.status != "completed",
                    or_(
                        getattr(DeletionCleanup, role + "_done").is_(False),
                        and_(
                            DeletionCleanup.source_done.is_(True),
                            DeletionCleanup.artifact_done.is_(True),
                        ),
                    ),
                )
                .limit(100)
            )
        )
        for job in jobs:
            db.refresh(job, with_for_update=True)
            if job.source_done and job.artifact_done:
                job.status, job.finished = "completed", time.time()
                db.commit()
            if getattr(job, role + "_done"):
                continue
            try:
                items = json.loads(job.manifest)
                if not isinstance(items, list) or len(items) > 10000:
                    raise ValueError("Invalid cleanup manifest")
                selected = [checked_item(item) for item in items if item["kind"] == role]
                requests = Path(cfg.source_dir if role == "source" else cfg.artifact_request_dir)
                result_name = cfg.parser_result_dir if role == "source" else cfg.artifact_result_dir
                for item in selected:
                    publish(requests, marker_name(item), item)
                if result_name:
                    results = Path(result_name)
                    safe_root(results)
                    if inline:
                        try:
                            consume_markers(requests, results, role)
                        except (ValueError, OSError, KeyError, TypeError):
                            pass  # Match offline loop: each job checks its own exact receipt.
                    if not (results / NAMESPACE).exists():
                        continue
                    safe_root(results / NAMESPACE)
                    acknowledged = True
                    for item in selected:
                        proof = results / NAMESPACE / receipt_name(item)
                        if not proof.exists():
                            acknowledged = False
                            break
                        if (
                            proof.is_symlink()
                            or not proof.is_file()
                            or proof.stat().st_size > 2000
                            or json.loads(proof.read_text()) != receipt(item)
                        ):
                            raise ValueError("Invalid cleanup receipt")
                    if not acknowledged:
                        continue
                elif role == "artifact":
                    raise ValueError("Artifact results missing")
                for item in selected:
                    if role == "source":
                        remove(requests, item["id"])
                        remove(requests, "inbox/" + str(item["id"]) + ".json")
                        remove(requests, "inbox/." + str(item["id"]) + ".tmp")
                    else:
                        remove(requests, item["id"] + "-" + str(item["revision"]))
                setattr(job, role + "_done", True)
                if job.source_done and job.artifact_done:
                    job.status, job.finished, job.error = "completed", time.time(), ""
                db.commit()
            except (ValueError, OSError, KeyError, TypeError):
                job.error = "Private Dateibereinigung ausstehend; Dateispeicher prüfen."
                db.commit()


def inline_cleanup(factory: Any, cfg: Settings) -> None:
    for role in ("source", "artifact"):
        process_pending(factory, cfg, role, inline=True)


def install_cleanup_api(app: FastAPI, factory: Any) -> None:
    from hub.knowledge_api import Auth

    @app.get("/api/deletions/{identifier}/status")
    def cleanup_status(identifier: uuid.UUID, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            row = db.get(DeletionCleanup, str(identifier))
            if row is None:
                raise HTTPException(404, "Dateibereinigung nicht gefunden")
            return {"id": row.id, "status": row.status, "error": row.error}
