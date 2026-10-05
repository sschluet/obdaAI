"""Canonical Markdown memory, explicit scope and compare-before-write reconciliation."""

import errno
import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hub.db import Memory, MemoryRevision

MARKER = re.compile(r"^<!-- obdaai-memory: (\{[^\n]+\}) -->\n")
MAX_NOTE = 200_000


def digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def vault_path(root: Path, relative: str) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Vault nicht verfügbar")
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in {"..", ".obsidian"} for p in parts):
        raise ValueError("Ungültiger Vault-Pfad")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlinks im Vault sind nicht zulässig")
    if root.resolve() not in current.resolve().parents:
        raise ValueError("Vault-Pfad außerhalb des freigegebenen Bereichs")
    return current


def revision(db: Session, row: Memory) -> None:
    if not db.get(MemoryRevision, (row.id, row.revision)):
        db.add(
            MemoryRevision(
                memory_id=row.id, revision=row.revision, content=row.content, sha256=row.sha256
            )
        )


def decode(content: str) -> tuple[str | None, str]:
    match = MARKER.match(content)
    if not match:
        return None, content
    try:
        data = json.loads(match[1])
        identifier = str(uuid.UUID(data["id"]))
        return identifier, content[match.end() :]
    except (ValueError, KeyError, TypeError):
        return None, content


def encoded(row: Memory) -> str:
    return "<!-- obdaai-memory: " + json.dumps({"id": row.id}) + " -->\n" + row.content


def serialize(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(791103043)"))


def validate_mount(root: Path, expected_fs: str = "") -> str | None:
    identity = None
    if expected_fs:
        try:
            mountinfo = Path("/proc/self/mountinfo").read_text()
        except OSError:
            raise ValueError("Kanonischer Vault-Mount nicht verfügbar; Index unverändert") from None
        for line in mountinfo.splitlines():
            fields, separator, details = line.partition(" - ")
            if separator and fields.split()[4] == str(root.absolute()):
                if details.split()[0] == expected_fs:
                    identity = fields.split()[0]
        if identity is None:
            raise ValueError("Kanonischer Vault-Mount nicht verfügbar; Index unverändert")
    try:
        vault_path(root, "AI/Memory")
    except OSError:
        raise ValueError("Kanonischer Vault nicht erreichbar; Index unverändert") from None
    return identity


def reconcile(
    db: Session,
    root: Path,
    *,
    allow_memory_writes: bool | None = None,
    expected_fs: str = "",
) -> dict[str, Any]:
    mount_identity = validate_mount(root, expected_fs)
    serialize(db)
    if allow_memory_writes:
        lock = vault_path(root, "AI/Memory/.obdaai-write.lock")
        lock.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        with lock.open("a+") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            result = _reconcile(db, root, allow_memory_writes=allow_memory_writes)
    else:
        result = _reconcile(db, root, allow_memory_writes=allow_memory_writes)
    if validate_mount(root, expected_fs) != mount_identity:
        raise ValueError("Vault-Mount während des Abgleichs geändert; Index unverändert")
    return result


def _reconcile(
    db: Session, root: Path, *, allow_memory_writes: bool | None = None
) -> dict[str, Any]:
    vault_path(root, "AI/Memory")
    found: set[str] = set()
    errors: list[str] = []
    # No followsymlinks; exclude Obsidian configuration and dotfolders.
    count = 0

    def unavailable(error: OSError) -> None:
        raise error  # Never interpret a disconnected/unreadable mount as deletion.

    for folder, dirs, files in os.walk(root, followlinks=False, onerror=unavailable):
        dirs[:] = sorted(
            d for d in dirs if not d.startswith(".") and not (Path(folder) / d).is_symlink()
        )
        for filename in sorted(files):
            if not filename.endswith(".md") or filename.startswith("."):
                continue
            count += 1
            if count > 5000:
                raise ValueError("Vault-Dateilimit überschritten; Index unverändert")
            relative = str((Path(folder) / filename).relative_to(root))
            try:
                path = vault_path(root, relative)
                if path.stat().st_size > MAX_NOTE:
                    errors.append(relative)
                    continue
                text = path.read_text(encoding="utf-8")
            except OSError as error:
                if error.errno in {
                    errno.EIO,
                    errno.ENOTCONN,
                    errno.ETIMEDOUT,
                    errno.ECONNRESET,
                    errno.ENETUNREACH,
                    errno.ESTALE,
                }:
                    raise  # A transport outage invalidates this whole scan.
                errors.append(relative)
                continue
            except (ValueError, UnicodeError):
                errors.append(relative)
                continue
            identity, body = decode(text)
            by_path = db.scalar(select(Memory).where(Memory.path == relative))
            row = db.get(Memory, identity) if identity else by_path
            if row is not None and row.id in found:
                row.conflict = "Doppelte Memory-ID im Vault; Dateien manuell vergleichen"
                continue
            if row is None:
                # Filename/hash matching supports a rename of ordinary read-only notes.
                candidates = list(db.scalars(select(Memory).where(Memory.sha256 == digest(body))))
                moved = [
                    m
                    for m in candidates
                    if not vault_path(root, m.path).exists() and m.id not in found and not m.deleted
                ]
                row = (
                    moved[0]
                    if len(moved) == 1
                    else Memory(
                        id=str(uuid.uuid4()),
                        path=relative,
                        content=body,
                        base_content=body,
                        sha256=digest(body),
                        writable=bool(allow_memory_writes and relative.startswith("AI/Memory/")),
                    )
                )
                db.add(row)
                db.flush()
            found.add(row.id)
            # Arbitrary vault files can never self-grant scope, privacy or writes.
            if not relative.startswith("AI/Memory/"):
                row.writable = False
            elif allow_memory_writes is not None:
                row.writable = allow_memory_writes
            if by_path is not None and by_path.id != row.id:
                row.conflict = "Zielpfad gehört zu anderem Memory"
                continue
            row.path = relative
            if row.conflict and row.conflict.startswith("pending:"):
                expected = row.conflict[len("pending:") :].removesuffix(":creating")
                if digest(body) == row.sha256:
                    row.conflict, row.base_content = "", body
                elif digest(body) != expected:
                    row.conflict = body
                elif row.writable and relative.startswith("AI/Memory/"):
                    # Complete an already approved persisted intent, never invent a new write.
                    temporary = path.parent / (".obdaai-" + str(uuid.uuid4()) + ".tmp")
                    try:
                        temporary.write_text(encoded(row), encoding="utf-8")
                        temporary.chmod(0o640)
                        _, latest = decode(path.read_text(encoding="utf-8"))
                        if digest(latest) == expected:
                            os.replace(temporary, path)
                            row.conflict, row.base_content = "", row.content
                        else:
                            row.conflict = latest
                    finally:
                        temporary.unlink(missing_ok=True)
            elif row.sha256 != digest(body):
                if row.conflict:
                    row.conflict = body
                else:
                    revision(db, row)
                    row.content, row.base_content = body, body
                    row.sha256, row.revision = digest(body), row.revision + 1
                    row.updated = time.time()
            row.deleted = False
            revision(db, row)
    # Never delete a note whose current path could not be read.
    for row in db.scalars(select(Memory)):
        if row.id not in found and row.path not in errors:
            if (
                row.conflict.startswith("pending:")
                and row.conflict.endswith(":creating")
                and row.writable
                and row.path.startswith("AI/Memory/")
            ):
                pending_path = vault_path(root, row.path)
                if not pending_path.exists():
                    pending_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
                    with pending_path.open("x", encoding="utf-8") as output:
                        output.write(encoded(row))
                        output.flush()
                        os.fsync(output.fileno())
                    pending_path.chmod(0o640)
                    row.conflict, row.base_content = "", row.content
                    row.deleted = False
                    continue
            row.deleted = True
            if row.conflict.startswith("pending:"):
                row.conflict = "Vault-Datei wurde während einer Änderung gelöscht"
    return {"files": count, "unreadable": errors, "synced_at": time.time()}


def write(db: Session, root: Path, row: Memory, content: str, expected_revision: int) -> None:
    serialize(db)
    if not row.writable or not row.path.startswith("AI/Memory/"):
        raise PermissionError("Schreiben ausschließlich in freigegebenem AI/Memory")
    if row.revision != expected_revision or row.deleted:
        raise ValueError("Memory geändert oder gelöscht; zuerst synchronisieren")
    lock = vault_path(root, "AI/Memory/.obdaai-write.lock")
    lock.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    with lock.open("a+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        if not db.is_modified(row):
            db.refresh(row)
        if row.revision != expected_revision or row.deleted:
            raise ValueError("Memory geändert oder gelöscht; zuerst synchronisieren")
        if not row.writable or not row.path.startswith("AI/Memory/"):
            raise PermissionError("Schreiben ausschließlich in freigegebenem AI/Memory")
        path = vault_path(root, row.path)
        path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        if path.exists():
            _, current = decode(path.read_text(encoding="utf-8"))
            if digest(current) != row.sha256:
                row.conflict = current
                db.commit()
                raise ValueError("Konflikt: Vault wurde verändert; Vergleich erforderlich")
        elif row.revision > 1 or row.base_content:
            row.deleted = True
            db.commit()
            raise ValueError("Memory im Vault gelöscht; keine Wiederbelebung")
        revision(db, row)
        previous = row.sha256
        row.content, row.sha256 = content, digest(content)
        row.revision += 1
        row.conflict = "pending:" + previous + (":creating" if not path.exists() else "")
        row.updated = time.time()
        revision(db, row)
        # Persist intent before atomic filesystem change; crash reconciles it.
        db.commit()
        temporary = path.parent / (".obdaai-" + str(uuid.uuid4()) + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(encoded(row))
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o640)
            # Recheck immediately before rename; external sync doesn't honor our lock.
            if path.exists():
                _, latest = decode(path.read_text(encoding="utf-8"))
                if digest(latest) != previous:
                    row.conflict = latest
                    db.commit()
                    raise ValueError("Konflikt während des Schreibens")
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            row.conflict, row.base_content = "", content
            db.commit()
        finally:
            temporary.unlink(missing_ok=True)
