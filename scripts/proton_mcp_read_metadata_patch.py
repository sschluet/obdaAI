"""Prepare an additive read-metadata patch for the pinned Proton MCP 0.4.0.

This command NEVER installs a patch, contacts a mailbox, restarts a service or
changes permissions. Its exclusive private output contains originals, proposed
sources and their hashes for a separately reviewed runtime deployment. Inputs are
source files only; no configuration, runtime data or credentials are read.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path

EXPECTED = {
    "models.py": "343535b09d2ff81fbab751f72ae26669cfd6e3f13cdf33ec94a7cf4f5edf7e2f",
    "parsing.py": "81339c5f9325d567c055b88921121009c861fd356857defdfbdd161af28a17df",
}


def patch_sources(sources: dict[str, bytes]) -> dict[str, bytes]:
    """Fail closed against exact current source pins; no file operations."""
    if set(sources) != set(EXPECTED):
        raise ValueError("Expected exactly the two pinned source files")
    for name, original in sources.items():
        if hashlib.sha256(original).hexdigest() != EXPECTED[name]:
            raise ValueError("Pinned source hash mismatch: " + name)
    models = sources["models.py"].decode()
    anchor = "    flagged: bool = False\n    size_bytes: int = 0\n"
    if models.count(anchor) != 1:
        raise ValueError("Unexpected summary model")
    models = models.replace(
        anchor,
        anchor + "    answered: bool | None = None\n"
        "    in_reply_to: str | None = None\n"
        "    references: str | None = None\n",
    )
    # References now belongs to every header summary and is inherited unchanged.
    duplicate = '    reply_to: str = ""\n    references: str = ""\n'
    if models.count(duplicate) != 1:
        raise ValueError("Unexpected content model")
    models = models.replace(duplicate, '    reply_to: str = ""\n')
    parsing = sources["parsing.py"].decode()
    anchor = '        flagged="\\\\Flagged" in flags,\n'
    if parsing.count(anchor) != 2:
        raise ValueError("Unexpected flag parsing")
    parsing = parsing.replace(
        anchor,
        anchor + '        answered="\\\\Answered" in flags,\n'
        '        in_reply_to=header_value(message, "In-Reply-To"),\n',
    )
    # Full messages already expose References. Add it only to summary parsing.
    summary_anchor = "        size_bytes=size,\n    )\n\n\ndef full_from_message("
    if parsing.count(summary_anchor) != 1:
        raise ValueError("Unexpected header parsing")
    parsing = parsing.replace(
        summary_anchor,
        "        size_bytes=size,\n"
        '        references=header_value(message, "References"),\n'
        "    )\n\n\ndef full_from_message(",
    )
    patched = {"models.py": models.encode(), "parsing.py": parsing.encode()}
    for name, content in patched.items():
        ast.parse(content, filename=name)
        compile(content, name, "exec")
    return patched


def prepare(source: Path, destination: Path) -> dict[str, object]:
    """Write a new private review bundle, never overwrite originals or runtime."""
    destination = destination.resolve()
    if any((parent / ".git").exists() for parent in (destination, *destination.parents)):
        # Private ignored runtime preparation is permitted; public trees are not.
        if ".local" not in destination.parts:
            raise ValueError("Review bundle must be outside a Git tree or under .local")
    originals = {name: (source / name).read_bytes() for name in EXPECTED}
    proposed = patch_sources(originals)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    manifest: dict[str, object] = {
        "upstream_version": "0.4.0",
        "upstream_commit": "f15d769d562de55c288a574f2a1e0946fefc9e31",
        "installed": False,
        "input_schemas_changed": False,
        "read_only_metadata_addition": True,
        "thread_completeness_verified": False,
        "files": {},
    }
    files = {}
    for name in EXPECTED:
        for suffix, content in (("original", originals[name]), ("proposed", proposed[name])):
            path = destination / (name + "." + suffix)
            with path.open("xb") as handle:
                path.chmod(0o600)
                handle.write(content)
        files[name] = {
            "original_sha256": EXPECTED[name],
            "proposed_sha256": hashlib.sha256(proposed[name]).hexdigest(),
        }
    manifest["files"] = files
    manifest_path = destination / "manifest.json"
    with manifest_path.open("x") as handle:
        manifest_path.chmod(0o600)
        handle.write(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.private_output)
    print("Prepared additive metadata sources; no runtime changes performed.")


if __name__ == "__main__":
    main()
