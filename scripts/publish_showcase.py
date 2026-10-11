"""Publish the validated public allowlist to the authorized website-only branch."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "sschluet/obdaAI"
PUBLISH_BRANCH = "gh-pages"


def command(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


if command("git", "status", "--porcelain"):
    raise SystemExit("Commit the reviewed delivery before publishing the website")
revision = command("git", "rev-parse", "HEAD")
branch = command("git", "branch", "--show-current")
runs = json.loads(
    command(
        "gh", "run", "list", "--workflow", "pages.yml", "--branch", branch,
        "--commit", revision, "--limit", "5", "--json", "status,conclusion",
    )
)
if not any(r["status"] == "completed" and r["conclusion"] == "success" for r in runs):
    raise SystemExit("The website CI for this exact delivery must pass before publication")
repo = json.loads(command("gh", "api", "repos/" + TARGET))
if repo["full_name"] != TARGET or repo["private"]:
    raise SystemExit("Expected the authorized public application repository")
if PUBLISH_BRANCH in {"main", "master", repo["default_branch"]}:
    raise SystemExit("Never publish over an application-source/default branch")
pages = json.loads(command("gh", "api", "repos/" + TARGET + "/pages"))
if pages.get("source") != {"branch": PUBLISH_BRANCH, "path": "/"}:
    raise SystemExit("Pages must publish the dedicated gh-pages branch root")
subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "build_showcase.py"), "--revision", revision],
    cwd=ROOT, check=True,
)
build = ROOT / ".local" / "website-build"
with tempfile.TemporaryDirectory(prefix="website-publish-", dir=ROOT / ".local") as folder:
    checkout = Path(folder) / "checkout"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", "--branch", PUBLISH_BRANCH,
         "https://github.com/" + TARGET + ".git",
         str(checkout)], check=True,
    )
    expected = {str(p.relative_to(build)) for p in build.rglob("*") if p.is_file()}
    existing = command("git", "ls-files", cwd=checkout).splitlines()
    allowed_old = expected | {"README.md"}
    if set(existing) - allowed_old:
        raise SystemExit("Unexpected files in the website repository; review before publishing")
    for name in existing:
        (checkout / name).unlink()
    for name in expected:
        destination = checkout / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(build / name, destination)
    (checkout / "README.md").write_text(
        "# obdaAI project website\n\n"
        "Public project presentation: https://sschluet.github.io/obdaAI/\n\n"
        "This gh-pages branch contains only the public website and synthetic UI screenshots. "
        "The application runtime, user documents and credentials remain private.\n\n"
        "Features, acceptance limits and screenshots are maintained with each application "
        "delivery. The public files are synchronized only after the exact website CI passes. "
        "GitHub Pages publishes updates from this repository automatically.\n"
    )
    command("git", "add", "--all", cwd=checkout)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=checkout)
    if diff.returncode == 0:
        print("Public website already matches this delivery")
    elif diff.returncode == 1:
        command(
            "git", "-c", "user.name=obdaAI Website", "-c",
            "user.email=sschluet@users.noreply.github.com", "commit", "-m",
            "Update project showcase from " + revision[:12], cwd=checkout,
        )
        subprocess.run(
            ["git", "push", "origin", "HEAD:refs/heads/" + PUBLISH_BRANCH],
            cwd=checkout, check=True,
        )
        print("Public showcase pushed for " + revision[:12])
    else:
        raise SystemExit("Could not inspect staged website changes")
