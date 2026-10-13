"""Immutable private skill packages. Imported helpers remain inert archive data."""

import hashlib
import io
import json
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from fastapi import HTTPException
from sqlalchemy.orm import Session

from hub.config import Settings
from hub.db import Skill, SkillRevision

MAX_PACKAGE = 20 * 1024 * 1024
MAX_UNPACKED = 80 * 1024 * 1024
MAX_FILES = 500
OFFICE = {".docx", ".dotx", ".pptx", ".potx", ".xlsx", ".xltx"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or len(name) > 240
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or any(p in ("..", ".") for p in name.split("/"))
        or re.match(r"^[A-Za-z]:", name)
    ):
        raise HTTPException(422, "Unsicherer Paketpfad")
    return str(path)


def entries(data: bytes, *, office: bool = False) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > (3000 if office else MAX_FILES):
                raise HTTPException(413, "Zu viele Paketdateien")
            result: dict[str, bytes] = {}
            total = 0
            for entry in infos:
                name = safe_path(entry.filename.rstrip("/"))
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode) or (
                    mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                ):
                    raise HTTPException(422, "Verknüpfungen im Paket sind nicht erlaubt")
                if entry.flag_bits & 1:
                    raise HTTPException(422, "Verschlüsselte Paketdateien sind nicht unterstützt")
                if entry.is_dir():
                    continue
                if name in result:
                    raise HTTPException(422, "Doppelter Paketpfad")
                total += entry.file_size
                if total > MAX_UNPACKED or entry.file_size > MAX_UNPACKED:
                    raise HTTPException(413, "Entpacktes Paket zu groß")
                if (
                    entry.file_size > 1024 * 1024
                    and entry.file_size > max(1, entry.compress_size) * 200
                ):
                    raise HTTPException(413, "Unzulässige Paketkompression")
                content = archive.read(entry)
                result[name] = content
            return result
    except (zipfile.BadZipFile, RuntimeError, OSError):
        raise HTTPException(422, "Ungültiges ZIP-Skillpaket") from None


def check_office(data: bytes) -> None:
    members = entries(data, office=True)
    if "[Content_Types].xml" not in members:
        raise HTTPException(422, "Ungültige Office-Vorlage")
    for name, content in members.items():
        if "vbaproject" in name.casefold() or "/embeddings/" in name.casefold():
            raise HTTPException(
                422, "Makros und eingebettete ausführbare Inhalte sind nicht erlaubt"
            )
        if name.endswith(".rels"):
            try:
                if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
                    raise ValueError
                root = ElementTree.fromstring(content)
                if any(x.attrib.get("TargetMode", "").casefold() == "external" for x in root):
                    raise HTTPException(422, "Externe Office-Verknüpfungen sind nicht erlaubt")
            except (ElementTree.ParseError, ValueError):
                raise HTTPException(422, "Ungültige Office-Verknüpfungen") from None


def inspect_package(data: bytes) -> tuple[str, dict[str, Any]]:
    from hub.skill_api import Metadata, parse, portable

    if not data or len(data) > MAX_PACKAGE:
        raise HTTPException(413, "Skillpaket maximal 20 MiB")
    files = entries(data)
    candidates = [p for p in files if PurePosixPath(p).name == "SKILL.md"]
    if len(candidates) != 1:
        raise HTTPException(422, "Paket braucht genau eine SKILL.md")
    try:
        raw = files[candidates[0]].decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "SKILL.md muss UTF-8 sein") from None
    warnings: list[str] = []
    try:
        meta, body = parse(raw)
    except HTTPException:
        # Only recover the known unquoted description colon; never accept tags/aliases/tools.
        try:
            front, body = raw.replace("\r\n", "\n")[4:].split("\n---\n", 1)
            lines = front.splitlines()
            fields: dict[str, str] = {}
            for line in lines:
                key, value = line.split(":", 1)
                if key not in ("name", "description") or key in fields:
                    raise ValueError
                fields[key] = value.strip()
            if set(fields) != {"name", "description"}:
                raise ValueError
            meta = Metadata(
                format="obdaai-skill-1", name=fields["name"], description=fields["description"]
            )
            parse(portable(meta, body))
            warnings.append("Beschreibung für Import normalisiert; Original unverändert")
        except (ValueError, HTTPException):
            raise HTTPException(422, "Ungültige Skill-Metadaten") from None
    meta.cloud_allowed = False
    meta.usage = "mention"
    manifest_files = []
    templates = []
    for path, content in files.items():
        extension = PurePosixPath(path).suffix.casefold()
        if extension in {".docm", ".dotm", ".pptm", ".potm", ".xlsm", ".xlam"}:
            raise HTTPException(422, "Makrodateien sind nicht erlaubt")
        kind = (
            "template"
            if extension in OFFICE
            else "script"
            if extension in {".py", ".sh", ".js"}
            else "reference"
            if extension in {".md", ".txt", ".json", ".yaml", ".yml"}
            else "asset"
        )
        item = {"path": path, "sha256": digest(content), "size": len(content), "kind": kind}
        manifest_files.append(item)
        if kind == "template":
            check_office(content)
            templates.append(item)
    dependencies = []
    if meta.name == "avendis-praesentation-modern":
        dependencies = ["avendis-praesentation"]
    manifest = {
        "format": "obdaai-bundle-1",
        "files": manifest_files,
        "templates": templates,
        "dependencies": dependencies,
        "warnings": warnings,
        "instructions_path": candidates[0],
        "scripts_executable": False,
        "privacy": "LOCAL_ONLY",
    }
    return portable(meta, body.strip()), manifest


def store(cfg: Settings, data: bytes) -> str:
    sha = digest(data)
    directory = Path(cfg.source_dir) / "skill-bundles"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / (sha + ".zip")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
    except FileExistsError:
        if path.is_symlink() or digest(path.read_bytes()) != sha:
            raise HTTPException(409, "Skillpaket beschädigt") from None
    return sha


def package_bytes(cfg: Settings, revision: SkillRevision) -> bytes:
    sha = revision.bundle_sha256
    if not sha or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(404, "Skillrevision hat kein Paket")
    path = Path(cfg.source_dir) / "skill-bundles" / (sha + ".zip")
    if path.is_symlink() or not path.is_file():
        raise HTTPException(409, "Skillpaket fehlt oder beschädigt")
    content = path.read_bytes()
    if digest(content) != sha:
        raise HTTPException(409, "Skillpaket beschädigt")
    return content


def file_bytes(cfg: Settings, revision: SkillRevision, path: str, sha256: str) -> bytes:
    safe_path(path)
    manifest = json.loads(revision.bundle_manifest)
    matches = [
        item
        for item in manifest.get("files", [])
        if item["path"] == path and item["sha256"] == sha256
    ]
    if len(matches) != 1:
        raise HTTPException(409, "Datei nicht an diese Skillrevision gebunden")
    files = entries(package_bytes(cfg, revision))
    content = files.get(path)
    if content is None or digest(content) != sha256:
        raise HTTPException(409, "Skilldatei beschädigt")
    return content


def resolve_template(
    db: Session, cfg: Settings, skill_id: str, revision: int, sha256: str, path: str | None = None
) -> Path:
    from hub.skill_api import eligible

    skill = db.get(Skill, skill_id)
    rev = db.get(SkillRevision, (skill_id, revision))
    if (
        skill is None
        or rev is None
        or skill.revision != revision
        or not eligible(skill, rev, skill.project_id)
    ):
        raise HTTPException(409, "Vorlage braucht aktive geprüfte Skillrevision")
    templates = json.loads(rev.bundle_manifest).get("templates", [])
    matches = [
        item
        for item in templates
        if (item["sha256"] == sha256 or rev.bundle_sha256 == sha256)
        and (path is None or item["path"] == path)
    ]
    if len(matches) != 1:
        raise HTTPException(409, "Vorlage nicht eindeutig an Skillrevision gebunden")
    item = matches[0]
    asset_sha = str(item["sha256"])
    content = file_bytes(cfg, rev, item["path"], asset_sha)
    directory = Path(cfg.source_dir) / "skill-bundles" / "assets"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = directory / (asset_sha + PurePosixPath(item["path"]).suffix.casefold())
    if target.exists():
        if target.is_symlink() or digest(target.read_bytes()) != asset_sha:
            raise HTTPException(409, "Vorlagenkopie beschädigt")
    else:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(content)
    return target
