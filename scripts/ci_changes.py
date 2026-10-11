"""Reuse only completed full-CI proofs for the actual checked-out application tree."""

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

LIGHT_ROOTS = {"README.md", "STATUS.md", "AGENTS.md"}
WEBSITE_FILES = {
    "scripts/build_showcase.py", "scripts/publish_showcase.py",
    "frontend/showcase-check.mjs", "frontend/capture-showcase.mjs",
    "frontend/capture-use-case-ai.mjs",
    ".github/workflows/pages.yml",
}
FULL_JOBS = {"python", "secrets", "frontend", "container", "browser-runner", "artifact-runner"}
API = "https://api.github.com"


def app_relevant(path: str) -> bool:
    return not (
        path in LIGHT_ROOTS or path in WEBSITE_FILES
        or path.startswith(("docs/", "website/"))
    )


def fingerprint(directory: Path | None = None) -> str:
    tree = subprocess.check_output(["git", "ls-tree", "-rz", "--full-tree", "HEAD"], cwd=directory)
    entries = []
    for entry in tree.split(b"\0"):
        if entry and app_relevant(entry.split(b"\t", 1)[1].decode("utf-8", "surrogateescape")):
            entries.append(entry)
    return hashlib.sha256(b"\0".join(sorted(entries))).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class GitHub:
    def __init__(self, token: str, repository: str):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository = repository
        self.headers = {
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "obdaAI-ci-proof",
        }

    def get(self, path: str) -> Any:
        request = urllib.request.Request(API + "/repos/" + self.repository + path,
                                         headers=self.headers)
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("Oversized API response")
            return json.loads(body)

    def proof(self, artifact_id: int) -> dict[str, Any]:
        url = API + "/repos/" + self.repository + f"/actions/artifacts/{artifact_id}/zip"
        request = urllib.request.Request(url, headers=self.headers)
        try:
            response = urllib.request.build_opener(NoRedirect).open(request, timeout=15)
        except urllib.error.HTTPError as error:
            if error.code != 302:
                raise
            location = error.headers.get("Location", "")
            error.close()
            if not location.startswith("https://"):
                raise ValueError("Invalid artifact redirect") from None
            # Signed storage URL receives NO GitHub Authorization header.
            response = urllib.request.urlopen(location, timeout=15)
        with response:
            archive = response.read(16_385)
        if len(archive) > 16_384:
            raise ValueError("Oversized proof archive")
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            info = bundle.getinfo("app-check-proof.json")
            if info.file_size > 4096:
                raise ValueError("Oversized proof")
            return json.loads(bundle.read(info))


def matching_proof(client: Any, current: str) -> dict[str, Any] | None:
    repo = client.get("")
    artifacts = client.get("/actions/artifacts?name=app-check-proof&per_page=30")["artifacts"]
    for artifact in artifacts:
        if artifact["expired"] or artifact["name"] != "app-check-proof":
            continue
        owner = artifact.get("workflow_run", {})
        if owner.get("head_repository_id") != repo["id"]:
            continue  # Never inherit proof from an untrusted fork's workflow.
        proof = client.proof(artifact["id"])
        if (
            proof.get("format") != 1 or proof.get("repository") != client.repository
            or proof.get("fingerprint") != current or proof.get("run_id") != owner["id"]
            or not re.fullmatch(r"[a-f0-9]{40}", proof.get("tested_sha", ""))
        ):
            continue
        run = client.get(f"/actions/runs/{owner['id']}")
        if (
            run["status"] != "completed" or run["conclusion"] != "success"
            or run["path"].split("@", 1)[0] != ".github/workflows/ci.yml"
            or run["head_repository"]["full_name"] != client.repository
        ):
            continue
        jobs = client.get(f"/actions/runs/{owner['id']}/jobs?per_page=100")["jobs"]
        results = {job["name"]: job["conclusion"] for job in jobs}
        if all(results.get(name) == "success" for name in FULL_JOBS):
            return proof
    return None


def decide(event: str, current: str, client: Any | None) -> tuple[bool, dict[str, Any] | None]:
    if event == "workflow_dispatch" or client is None:
        return True, None
    try:
        proof = matching_proof(client, current)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        print("CI proof unavailable; full application checks required.")
        return True, None
    return proof is None, proof


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    current = fingerprint()
    if args.record:
        proof = {
            "format": 1, "repository": os.environ["GITHUB_REPOSITORY"],
            "run_id": int(os.environ["GITHUB_RUN_ID"]), "fingerprint": current,
            "tested_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        }
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(proof) + "\n")
        return
    token = os.getenv("CI_GITHUB_TOKEN", "")
    client = GitHub(token, os.environ["GITHUB_REPOSITORY"]) if token else None
    full, proof = decide(os.getenv("GITHUB_EVENT_NAME", ""), current, client)
    output = f"app={'true' if full else 'false'}\nfingerprint={current}\n"
    if proof:
        output += f"validated_run={proof['run_id']}\nvalidated_sha={proof['tested_sha']}\n"
        print(f"App tree already validated by full CI run {proof['run_id']}.")
    else:
        print("No matching completed full-CI proof; application checks required.")
    if path := os.getenv("GITHUB_OUTPUT"):
        with Path(path).open("a") as stream:
            stream.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
