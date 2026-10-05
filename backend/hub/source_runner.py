"""Offline container: originals read-only, no DB/provider/vault secrets or network."""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from hub.extract import EXTENSIONS, isolated_parse


def process(root: Path, output: Path, job: Path) -> None:
    if job.is_symlink() or job.stat().st_size > 2000:
        return
    try:
        spec = json.loads(job.read_text())
        identifier = str(uuid.UUID(spec["id"]))
        digest = spec["sha256"]
        suffix = spec["suffix"]
        if (
            len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or suffix not in EXTENSIONS
            or job.name != identifier + ".json"
        ):
            return
        original = root / identifier / digest
        if original.is_symlink() or original.parent.is_symlink():
            return
        result_file = output / (identifier + ".json")
        if result_file.exists():
            return
        if hashlib.sha256(original.read_bytes()).hexdigest() != digest:
            raise ValueError("Original verändert")
        result = isolated_parse(original, suffix)
        result["sha256"] = digest
    except (ValueError, OSError, KeyError, TimeoutError):
        result = {"error": "Extraktion fehlgeschlagen; Format, Schutz, OCR und Limits prüfen"}
        identifier = job.stem
    temporary = output / ("." + identifier + ".tmp")
    temporary.write_text(json.dumps(result))
    os.replace(temporary, output / (identifier + ".json"))


def main() -> None:
    root, output = Path("/sources"), Path("/results")
    while True:
        for job in sorted((root / "inbox").glob("*.json"))[:10000]:
            process(root, output, job)
        time.sleep(1)


if __name__ == "__main__":
    main()
