"""Durable artifact dispatch and verification across the offline file boundary."""

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.artifact_render import MAX_INPUT, MAX_OUTPUT
from hub.artifact_runner import canonical
from hub.artifact_specs import ArtifactSpec
from hub.config import Settings
from hub.db import Artifact, ArtifactRevision, Project, Source
from hub.knowledge import original


class PreviewFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1, le=100)
    filename: str = Field(pattern=r"^previews/page-[0-9]{1,3}\.png$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0, le=MAX_OUTPUT)


class OutputManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(pattern=r"^artifact\.(docx|pptx|pdf|png|jpeg)$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0, le=MAX_OUTPUT)
    label: str = Field(pattern=r"^LOCAL_ONLY$")
    preview_verified: bool
    previews: list[PreviewFile] = Field(min_length=1, max_length=100)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str = Field(pattern=r"^needs_review$")


def roots(cfg: Settings) -> tuple[Path, Path]:
    if not cfg.artifact_request_dir or not cfg.artifact_result_dir:
        raise ValueError("Lokaler Dateirunner ist noch nicht eingerichtet")
    paths = Path(cfg.artifact_request_dir), Path(cfg.artifact_result_dir)
    for path in paths:
        if not path.is_dir() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError("Privater Dateirunner-Pfad fehlt oder ist ungültig")
    return paths


def digest(document: str) -> str:
    return hashlib.sha256(document.encode()).hexdigest()


def storage_bytes(cfg: Settings) -> int:
    used, count = 0, 0
    for root in roots(cfg):
        for path in root.rglob("*"):
            count += 1
            if count > 30000 or path.is_symlink():
                raise ValueError("Dateispeicher benötigt eine Integritätsprüfung")
            if path.is_file():
                used += path.stat().st_size
    return used


def spec_for(row: ArtifactRevision) -> ArtifactSpec:
    if digest(row.spec) != row.spec_sha256:
        raise ValueError("Artefaktvorgabe wurde verändert")
    return ArtifactSpec.model_validate_json(row.spec)


def bind_sources(db: Session, cfg: Settings, project_id: str, spec: ArtifactSpec) -> list[Path]:
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if not project or project.archived:
        raise ValueError("Aktiver Projektraum fehlt")
    paths = []
    total = 0
    for binding in spec.sources:
        source = db.scalar(select(Source).where(Source.id == binding.id).with_for_update())
        if not source or source.project_id != project_id:
            raise ValueError("Quelle gehört nicht zu diesem Projektraum")
        if source.revision != binding.revision or source.sha256 != binding.sha256:
            raise ValueError("Quellenrevision wurde verändert")
        path = original(cfg, source)
        total += path.stat().st_size
        if total > 100 * 1024 * 1024 or path.stat().st_size > MAX_INPUT:
            raise ValueError("Maximal 100 MiB gebundene Quellen je Artefakt")
        paths.append(path)
    return paths


def job_name(row: ArtifactRevision) -> str:
    return str(uuid.UUID(row.artifact_id)) + "-" + str(row.revision)


def spool(db: Session, cfg: Settings, artifact: Artifact, row: ArtifactRevision) -> None:
    requests, _ = roots(cfg)
    spec = spec_for(row)
    inputs = bind_sources(db, cfg, artifact.project_id, spec)
    target = requests / job_name(row)
    if target.exists():
        path = target / "spec.json"
        if target.is_symlink() or path.is_symlink() or path.read_text() != canonical(spec):
            raise ValueError("Abweichender Dateiauftrag existiert bereits")
        from hub.artifact_render import verified_inputs

        verified_inputs(spec, [target / ("source-" + str(i)) for i in range(len(inputs))])
        return
    temporary = requests / ("." + job_name(row) + "-" + str(uuid.uuid4()))
    temporary.mkdir(mode=0o700)
    try:
        for number, source in enumerate(inputs):
            destination = temporary / ("source-" + str(number))
            with destination.open("xb") as stream:
                stream.write(source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            destination.chmod(0o400)
        path = temporary / "spec.json"
        with path.open("x") as stream:
            stream.write(canonical(spec))
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o400)
        os.rename(temporary, target)
    except Exception:
        for path in temporary.iterdir():
            path.unlink()
        temporary.rmdir()
        raise


def output_file(cfg: Settings, row: ArtifactRevision, filename: str, sha256: str) -> Path:
    _, results = roots(cfg)
    pattern = r"artifact\.(docx|pptx|pdf|png|jpeg)|previews/page-[0-9]{1,3}\.png"
    if not re.fullmatch(pattern, filename):
        raise ValueError("Ungültige Ausgabedatei")
    path = results / job_name(row) / "version" / filename
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("Verknüpfte Ausgabedatei")
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_OUTPUT:
        raise ValueError("Ausgabedatei fehlt oder ist zu groß")
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        raise ValueError("Ausgabedatei wurde verändert")
    return path


def checked_manifest(cfg: Settings, row: ArtifactRevision, raw: str) -> OutputManifest:
    manifest = OutputManifest.model_validate_json(raw)
    spec = spec_for(row)
    if manifest.spec_sha256 != row.spec_sha256 or manifest.preview_verified:
        raise ValueError("Dateiauftrag passt nicht zur Vorschau")
    suffix = spec.plan.format if spec.plan.kind == "image" else spec.plan.kind
    if manifest.filename != "artifact." + suffix:
        raise ValueError("Ausgabeformat passt nicht zur Vorgabe")
    expected = (
        len(spec.plan.slides)
        if spec.plan.kind == "pptx"
        else len(spec.plan.pages)
        if spec.plan.kind == "pdf"
        else 1
        if spec.plan.kind == "image"
        else len(manifest.previews)
    )
    if len(manifest.previews) != expected:
        raise ValueError("Vorschau ist unvollständig")
    if sum(p.bytes for p in manifest.previews) > 100 * 1024 * 1024:
        raise ValueError("Vorschauen überschreiten das Größenlimit")
    output = output_file(cfg, row, manifest.filename, manifest.sha256)
    if output.stat().st_size != manifest.bytes:
        raise ValueError("Dateigröße passt nicht zum Beleg")
    from PIL import Image

    for number, preview in enumerate(manifest.previews, 1):
        if preview.page != number or int(Path(preview.filename).stem.split("-")[-1]) != number:
            raise ValueError("Vorschauseiten sind nicht eindeutig geordnet")
        path = output_file(cfg, row, preview.filename, preview.sha256)
        if path.stat().st_size != preview.bytes:
            raise ValueError("Vorschaugröße passt nicht zum Beleg")
        with Image.open(path) as image:
            if image.format != "PNG" or max(image.size) > 1400:
                raise ValueError("Ungültiges Vorschaubild")
            image.verify()
    return manifest


def reconcile(db: Session, cfg: Settings, row: ArtifactRevision) -> None:
    if row.status not in {"queued", "rendering"}:
        return
    _, results = roots(cfg)
    path = results / job_name(row) / "manifest.json"
    if not path.exists():
        if row.started and time.time() - row.started > 180:
            row.status, row.error = "failed", "Dateierstellung unterbrochen; neue Version anlegen"
        return
    try:
        if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 100_000:
            raise ValueError("Ungültiger Ausgabebeleg")
        raw = path.read_text()
        data = json.loads(raw)
        if data.get("status") == "failed":
            raise ValueError("Datei oder Vorschau konnte nicht erstellt werden")
        manifest = checked_manifest(cfg, row, raw)
        artifact = db.get(Artifact, row.artifact_id)
        if not artifact:
            raise ValueError("Artefakt fehlt")
        bind_sources(db, cfg, artifact.project_id, spec_for(row))
        row.manifest = manifest.model_dump_json()
        row.status = "needs_review"
    except (ValueError, OSError, KeyError, TypeError):
        row.status = "failed"
        row.error = "Datei, Quellenbindung oder Vorschauprüfung fehlgeschlagen"


async def execute_artifact(
    factory: sessionmaker[Session], cfg: Settings, artifact_id: str, revision: int
) -> None:
    with factory() as db:
        artifact = db.get(Artifact, artifact_id)
        if not artifact:
            return
        db.scalar(select(Project).where(Project.id == artifact.project_id).with_for_update())
        row = db.scalar(
            select(ArtifactRevision)
            .where(
                ArtifactRevision.artifact_id == artifact_id,
                ArtifactRevision.revision == revision,
            )
            .with_for_update()
        )
        if not row or row.status not in {"queued", "rendering"}:
            return
        try:
            if row.status == "queued":
                spool(db, cfg, artifact, row)
                row.status, row.started = "rendering", time.time()
            else:
                # A restarted worker reconciles the same immutable request; it
                # never resets the deadline or creates another output version.
                reconcile(db, cfg, row)
        except (ValueError, OSError):
            row.status, row.error = "failed", "Dateiauftrag oder Quellenbindung fehlgeschlagen"
        db.commit()
        if row.status != "rendering":
            return
    for _ in range(180):
        with factory() as db:
            artifact = db.get(Artifact, artifact_id)
            if not artifact:
                return
            db.scalar(select(Project).where(Project.id == artifact.project_id).with_for_update())
            row = db.scalar(
                select(ArtifactRevision)
                .where(
                    ArtifactRevision.artifact_id == artifact_id,
                    ArtifactRevision.revision == revision,
                )
                .with_for_update()
            )
            if not row or row.status != "rendering":
                return
            reconcile(db, cfg, row)
            db.commit()
            if row.status != "rendering":
                return
        await asyncio.sleep(1)


def info(row: ArtifactRevision) -> dict[str, Any]:
    spec = spec_for(row)
    return {
        "artifact_id": row.artifact_id,
        "revision": row.revision,
        "title": spec.plan.title,
        "kind": spec.plan.kind,
        "label": "LOCAL_ONLY",
        "spec": spec.model_dump(mode="json"),
        "spec_sha256": row.spec_sha256,
        "status": row.status,
        "error": row.error,
        "created": row.created,
        "accepted": row.accepted,
        "draft": json.loads(row.draft_metadata) if row.draft_metadata else None,
        "chat": {
            key: value for key, value in json.loads(row.chat_metadata).items() if key != "content"
        }
        if row.chat_metadata
        else None,
        "output": json.loads(row.manifest) if row.manifest else None,
    }
