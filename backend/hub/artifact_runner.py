"""Offline, bounded artifact spool consumer. No credentials, DB or network mounts."""

import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from hub.artifact_preview import previews
from hub.artifact_render import render
from hub.artifact_specs import ArtifactSpec
from hub.deletion_cleanup import blocked, consume_markers, remove
from hub.parser_sandbox import restrict


def canonical(spec: ArtifactSpec) -> str:
    return json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def child(request: Path, output: Path) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_FSIZE, (40 * 1024 * 1024, 40 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    # Landlock binds this child to one request and one output. The container also
    # has no network, sockets, secrets, database, vault or general source volume.
    output.mkdir(mode=0o700)
    for name in ("HOME", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
        os.environ[name] = str(output.resolve())
    restrict(request, output, office=True)
    spec = ArtifactSpec.model_validate_json((request / "spec.json").read_bytes())
    inputs = [
        request / ("source-" + str(i)) for i in range(len(spec.sources) + bool(spec.template))
    ]
    manifest = render(spec, inputs, output / "version")
    path = output / "version" / manifest["filename"]
    manifest["previews"] = previews(path.with_suffix(".pdf") if manifest.get("parts") else path)
    if spec.plan.kind == "docx" and spec.plan.pdf_export:
        pdf = output / "version" / "previews" / "artifact.pdf"
        pdf.chmod(0o400)
        manifest["pdf_export"] = {
            "filename": "previews/artifact.pdf",
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "bytes": pdf.stat().st_size,
        }
    manifest["spec_sha256"] = hashlib.sha256(canonical(spec).encode()).hexdigest()
    # Rendering proves files are previewable, not that their contents were
    # visually accepted. The application must show them for explicit review.
    manifest["status"] = "needs_review"
    target = output / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    target.chmod(0o400)


def process(request: Path, results: Path) -> bool:
    if request.is_symlink() or not request.is_dir():
        return False
    try:
        identifier, revision = request.name.rsplit("-", 1)
        if str(uuid.UUID(identifier)) != identifier or not 1 <= int(revision) <= 100000:
            return False
        if blocked(request.parent, "artifact", identifier, int(revision)):
            return False
        spec_path = request / "spec.json"
        if spec_path.is_symlink() or not 0 < spec_path.stat().st_size <= 800_000:
            return False
        spec = ArtifactSpec.model_validate_json(spec_path.read_bytes())
    except (ValueError, OSError):
        return False
    target = results / request.name
    if target.exists() or target.is_symlink():
        return False  # Published versions are immutable; no replayed overwrites.
    temporary = results / ("." + request.name + "-pending")
    if temporary.exists() or temporary.is_symlink():
        # Never interpret an interrupted render as a complete preview. Preserve
        # its data for reconciliation; retry requires a fresh explicit version.
        result: dict[str, Any] = {"status": "failed", "error": "Vorschau unterbrochen"}
        failure = results / ("." + request.name + "-failure")
        if failure.exists():
            return False
        failure.mkdir(mode=0o700)
        (failure / "manifest.json").write_text(json.dumps(result))
        os.rename(failure, target)
        return True
    task = subprocess.Popen(
        [sys.executable, "-m", "hub.artifact_runner", "--child", str(request), str(temporary)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 150
    exceeded = False
    while True:
        used, count = 0, 0
        for path in temporary.rglob("*"):
            count += 1
            try:
                used += path.lstat().st_size
            except FileNotFoundError:
                continue  # Profile/cache file removed during the bounded scan.
            if count > 5000 or used > 220 * 1024 * 1024 or path.is_symlink():
                exceeded = True
                break
        if exceeded or time.monotonic() >= deadline:
            try:
                os.killpg(task.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            task.wait()
            exceeded = True
            break
        if task.poll() is not None:
            break
        time.sleep(0.25)
    code = -1 if exceeded else task.wait()
    if not temporary.exists():
        temporary.mkdir(mode=0o700)
    if code != 0:
        (temporary / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "error": "Datei oder Vorschau konnte nicht erstellt werden",
                    "spec_sha256": hashlib.sha256(canonical(spec).encode()).hexdigest(),
                }
            )
        )
    if blocked(request.parent, "artifact", identifier, int(revision)):
        remove(results, temporary.name)
        return False
    os.rename(temporary, target)
    return True


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    if len(sys.argv) != 1:
        raise ValueError("Ungültige Runner-Argumente")
    requests, results = Path("/requests"), Path("/results")
    while True:
        try:
            consume_markers(requests, results, "artifact")
        except (ValueError, OSError, KeyError, TypeError):
            pass  # Durable DB owner reports a missing cleanup acknowledgement.
        for request in sorted(requests.iterdir())[:10000]:
            process(request, results)
        time.sleep(1)


if __name__ == "__main__":
    main()
