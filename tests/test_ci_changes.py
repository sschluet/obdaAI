"""CI must not mistake canceled/partial/fork runs for a validated application tree."""

import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

_spec = importlib.util.spec_from_file_location(
    "ci_changes", Path(__file__).resolve().parents[1] / "scripts/ci_changes.py"
)
_ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ci)
FULL_JOBS = _ci.FULL_JOBS
GitHub = _ci.GitHub
app_relevant = _ci.app_relevant
decide = _ci.decide
fingerprint = _ci.fingerprint
matching_proof = _ci.matching_proof


class FakeGitHub:
    repository = "sschluet/obdaAI"

    def __init__(self):
        self.artifact = {
            "name": "app-check-proof",
            "id": 7,
            "expired": False,
            "workflow_run": {"id": 10, "head_repository_id": 20},
        }
        self.document = {
            "format": 1,
            "repository": self.repository,
            "run_id": 10,
            "fingerprint": "current-tree",
            "tested_sha": "a" * 40,
        }
        self.run = {
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/ci.yml",
            "head_repository": {"full_name": self.repository},
        }
        self.jobs = [{"name": name, "conclusion": "success"} for name in FULL_JOBS]

    def get(self, path):
        if path == "":
            return {"id": 20}
        if path.startswith("/actions/artifacts?"):
            return {"artifacts": [self.artifact]}
        if path.endswith("/jobs?per_page=100"):
            return {"jobs": self.jobs}
        return self.run

    def proof(self, identifier):
        return self.document


class CIProofTests(unittest.TestCase):
    def test_known_documents_and_website_only_but_runtime_markdown_is_code(self):
        for path in [
            "README.md",
            "STATUS.md",
            "AGENTS.md",
            "docs/routing.md",
            "website/assets/chat.png",
            "scripts/publish_showcase.py",
            "frontend/capture-use-case-ai.mjs",
            "frontend/capture-paperless.mjs",
            "frontend/capture-use-case-stages.mjs",
            "frontend/capture-cloud-balances.mjs",
            ".github/workflows/pages.yml",
            "frontend/showcase-check.mjs",
        ]:
            with self.subTest(path=path):
                self.assertFalse(app_relevant(path))
        for path in [
            "backend/hub/auth.py",
            "frontend/src/main.tsx",
            "uv.lock",
            "frontend/pnpm-lock.yaml",
            "Dockerfile",
            "deploy/compose.yaml",
            "skills/SKILL.md",
            "unknown-root-file",
            "scripts/ci_changes.py",
            ".github/workflows/ci.yml",
            "tests/test_ci_changes.py",
        ]:
            with self.subTest(path=path):
                self.assertTrue(app_relevant(path))

    def test_only_matching_completed_six_job_proof_allows_reuse(self):
        client = FakeGitHub()
        self.assertEqual(matching_proof(client, "current-tree"), client.document)
        self.assertFalse(decide("pull_request", "current-tree", client)[0])
        self.assertIsNone(matching_proof(client, "changed-tree"))

    def test_canceled_unfinished_or_failed_code_run_requires_full_successor(self):
        for status, conclusion in [
            ("in_progress", None),
            ("completed", "cancelled"),
            ("completed", "failure"),
        ]:
            with self.subTest(status=status, conclusion=conclusion):
                client = FakeGitHub()
                client.run.update(status=status, conclusion=conclusion)
                self.assertTrue(decide("pull_request", "current-tree", client)[0])

    def test_skipped_or_missing_app_job_cannot_prove_full_validation(self):
        client = FakeGitHub()
        client.jobs[0]["conclusion"] = "skipped"
        self.assertIsNone(matching_proof(client, "current-tree"))
        client.jobs = []
        self.assertIsNone(matching_proof(client, "current-tree"))

    def test_expired_fork_wrong_repository_or_wrong_workflow_proof_rejected(self):
        for field, value in [("expired", True), ("name", "unrelated")]:
            client = FakeGitHub()
            client.artifact[field] = value
            self.assertIsNone(matching_proof(client, "current-tree"))
        client = FakeGitHub()
        client.artifact["workflow_run"]["head_repository_id"] = 21
        self.assertIsNone(matching_proof(client, "current-tree"))
        client = FakeGitHub()
        client.document["repository"] = "another/repository"
        self.assertIsNone(matching_proof(client, "current-tree"))
        client = FakeGitHub()
        client.run["path"] = ".github/workflows/unrelated.yml"
        self.assertIsNone(matching_proof(client, "current-tree"))

    def test_missing_auth_api_failure_and_manual_dispatch_fail_closed(self):
        self.assertTrue(decide("push", "current-tree", None)[0])
        client = Mock()
        client.get.side_effect = urllib.error.HTTPError("", 403, "denied", {}, None)
        self.assertTrue(decide("pull_request", "current-tree", client)[0])
        self.assertTrue(decide("workflow_dispatch", "current-tree", FakeGitHub())[0])

    def test_artifact_storage_never_receives_api_authorization_header(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("app-check-proof.json", json.dumps({"format": 1}))
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            "", 302, "found", {"Location": "https://storage.example/proof"}, None
        )
        with (
            patch("urllib.request.build_opener", return_value=opener),
            patch("urllib.request.urlopen", return_value=io.BytesIO(archive.getvalue())) as storage,
        ):
            self.assertEqual(GitHub("synthetic", "sschluet/obdaAI").proof(7), {"format": 1})
            storage.assert_called_once_with("https://storage.example/proof", timeout=15)

    def test_actual_git_tree_docs_insensitive_code_modes_and_moves_sensitive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args):
                subprocess.run(
                    ["git", "-C", folder, *args],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            def commit():
                git("add", ".")
                git("commit", "-m", "synthetic")

            git("init")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "user.name", "Synthetic CI")
            (root / "backend").mkdir()
            (root / "backend/app.py").write_text("pass\n")
            (root / "README.md").write_text("first\n")
            commit()
            original = fingerprint(root)
            (root / "README.md").write_text("documentation only\n")
            commit()
            self.assertEqual(original, fingerprint(root))
            (root / "backend/app.py").write_text("print('changed')\n")
            commit()
            changed = fingerprint(root)
            self.assertNotEqual(original, changed)
            git("update-index", "--chmod=+x", "backend/app.py")
            git("commit", "-m", "mode")
            self.assertNotEqual(changed, fingerprint(root))
            (root / "docs").mkdir()
            git("mv", "backend/app.py", "docs/app.py")
            git("commit", "-m", "move")
            self.assertNotEqual(original, fingerprint(root))


if __name__ == "__main__":
    unittest.main()
