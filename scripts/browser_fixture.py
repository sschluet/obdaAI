"""Synthetic test server; never a deployment configuration or live model test."""

import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import hub.action_api as fixture_action_api
import hub.artifact_api as fixture_artifact_api
import hub.browser_read as fixture_browser
import hub.chat_tools as fixture_chat_tools
import hub.ha_maintenance as fixture_maintenance
from alembic import command
from alembic.config import Config
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import Artifact, ArtifactRevision
from hub.mcp_client import schema_digest
from hub.policy import CloudGrant, ContextPart
from hub.routing import Route

folder = Path(os.getenv("HUB_BROWSER_FIXTURE_DIR", ".local/browser"))
folder.mkdir(parents=True, exist_ok=True)
artifact_requests = folder / "artifact-requests"
artifact_results = folder / "artifact-results"
artifact_requests.mkdir(exist_ok=True)
artifact_results.mkdir(exist_ok=True)
vault = folder / "vault"
vault.mkdir(exist_ok=True)
key_file = folder / "fixture-encryption.key"
if not key_file.exists():
    key_file.write_text(base64.b64encode(os.urandom(32)).decode())
    key_file.chmod(0o600)
os.environ["HUB_DATABASE_URL"] = "sqlite:///" + str(folder / "fixture.sqlite")
command.upgrade(Config("alembic.ini"), "head")
app = create_app(
    Settings(
        database_url=os.environ["HUB_DATABASE_URL"],
        mcp_endpoints_json=json.dumps(
            {os.getenv("HUB_BROWSER_ORIGIN", "http://127.0.0.1:18765") + "/mcp": "127.0.0.1"}
        ),
        mcp_read_tools_json=json.dumps(
            {
                os.getenv("HUB_BROWSER_ORIGIN", "http://127.0.0.1:18765") + "/mcp": {
                    "synthetic.read": schema_digest(
                        {"type": "object", "additionalProperties": False}
                    )
                }
            }
        ),
        browser_targets_json=json.dumps(
            {
                "synthetic": {
                    "name": "Synthetic public page",
                    "url": "https://example.org/help",
                    "ip": "93.184.215.14",
                }
            }
        ),
        browser_request_dir="synthetic-only",
        browser_result_dir="synthetic-only",
        origin=os.getenv("HUB_BROWSER_ORIGIN", "http://127.0.0.1:18765"),
        secure_cookie=False,
        password_hash=password_hash("synthetic-ui-password"),
        secrets_key_file=str(key_file),
        ha_token_file="synthetic-fixture-only",
        ha_allowed_ip="192.0.2.1",
        source_dir=str(folder / "sources"),
        artifact_request_dir=str(artifact_requests),
        artifact_result_dir=str(artifact_results),
        vault_dir=str(vault),
        vault_writable=True,
        search_url=os.getenv("HUB_BROWSER_ORIGIN", "http://127.0.0.1:18765") + "/search",
        search_allowed_ip="127.0.0.1",
        local_base_url=os.getenv("HUB_BROWSER_ORIGIN", "http://127.0.0.1:18765") + "/v1",
        local_allowed_ip="127.0.0.1",
        local_model="synthetic-fixture",
        local_disable_thinking=True,
    )
)


async def synthetic_artifact(factory, cfg, artifact_id, revision):
    # UI boundary fixture only. Real Office/Poppler preview acceptance belongs to
    # the separate Linux offline-runner test, never to this synthetic image.
    import hashlib

    from hub.artifact_render import render
    from hub.artifacts import reconcile, spec_for, spool
    from PIL import Image, ImageDraw

    with factory() as db:
        row = db.get(ArtifactRevision, (artifact_id, revision))
        artifact = db.get(Artifact, artifact_id)
        if not row or not artifact or row.status != "queued":
            return
        spool(db, cfg, artifact, row)
        row.status = "rendering"
        db.commit()
        spec = spec_for(row)
        request = artifact_requests / (artifact_id + "-" + str(revision))
        output = artifact_results / request.name
        output.mkdir()
        manifest = render(
            spec,
            [request / ("source-" + str(i)) for i in range(len(spec.sources))],
            output / "version",
        )
        manifest["spec_sha256"] = row.spec_sha256
        manifest["status"] = "needs_review"
        previews = output / "version/previews"
        previews.mkdir()
        count = (
            len(spec.plan.slides)
            if spec.plan.kind == "pptx"
            else (len(spec.plan.pages) if spec.plan.kind == "pdf" else 1)
        )
        manifest["previews"] = []
        for page in range(1, count + 1):
            path = previews / ("page-" + str(page) + ".png")
            image = Image.new("RGB", (600, 400), "#f4f7fd")
            ImageDraw.Draw(image).text(
                (25, 30), "SYNTHETIC UI PREVIEW - not layout acceptance", fill="#153976"
            )
            image.save(path)
            manifest["previews"].append(
                {
                    "page": page,
                    "filename": "previews/" + path.name,
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        (output / "manifest.json").write_text(json.dumps(manifest))
        reconcile(db, cfg, row)
        db.commit()


fixture_artifact_api.execute_artifact = synthetic_artifact


class SyntheticProvider:
    async def title(self, parts: list[ContextPart], roles: list[str]) -> str:
        await asyncio.sleep(2)
        return "Synthetic automatic title"

    async def route(self, parts: list[ContextPart], roles: list[str]) -> Route:
        if any("SYNTHETIC_TASK_PLAN" in p.content for p in parts):
            return Route(capabilities=["task"], model_class="cloud", reason="synthetic planning")
        if any("SYNTHETIC_HA_QUERY" in p.content for p in parts):
            return Route(
                capabilities=["tool"],
                model_class="cloud",
                reason="synthetic HA read",
                read_tool="ha.maintenance.plan",
            )
        if any("SYNTHETIC_WEB_QUERY" in p.content for p in parts):
            return Route(
                capabilities=["web"],
                model_class="local",
                reason="synthetic web fixture",
                answer=None,
            )
        if any("SYNTHETIC_SLOW" in p.content for p in parts):
            await asyncio.sleep(3)
        return Route(
            capabilities=["chat"],
            model_class="local",
            reason="synthetic browser fixture",
            answer=(
                "SYNTHETIC_BROWSER_REPLY: **Antwort** mit einer Tabelle.\n\n"
                "| A | B |\n|---|---|\n| 1 | 2 |"
            ),
        )

    async def stream(
        self,
        parts: list[ContextPart],
        roles: list[str],
        *,
        external: bool,
        grants: list[CloudGrant],
    ) -> AsyncIterator[str]:
        if parts and parts[0].source_id == "task-draft-policy":
            assert not external and not grants
            if "SYNTHETIC_TASK_PLAN" in parts[-1].content:
                yield json.dumps(
                    {
                        "title": "Synthetischer HA Wochenbericht",
                        "kind": "ha_maintenance",
                        "schedule": {
                            "kind": "weekly",
                            "time": "02:00",
                            "weekdays": [5],
                            "timezone": "Europe/Berlin",
                        },
                    }
                )
                return
            yield '{"title":"Synthetischer lokaler Analyseentwurf"}'
            return
        if any(p.source_id.startswith("tool:") for p in parts):
            assert not external
            yield "SYNTHETIC_HA_CHAT_REPLY: Wartungsbericht gespeichert, keine Änderungen."
            return
        if parts and parts[0].source_id == "task-policy":
            assert not external and not grants
            yield "SYNTHETIC_TASK_REPLY: eine lokale Aufgabenanalyse."
            return
        if not any(p.content.startswith(("Projekt:", "VAULT ", "WEBQUELLE ")) for p in parts):
            raise RuntimeError("Simple synthetic fixture must not make a second model call")
        yield "SYNTHETIC_SOURCE_REPLY: project-only evidence."
        for part in parts:
            if part.content.startswith("QUELLE"):
                yield "\n" + part.content.split("\n")[0]


app.state.providers = SyntheticProvider()


@app.get("/v1/models")
def fixture_models() -> dict[str, object]:
    return {"data": [{"id": "synthetic-fixture"}]}


@app.post("/v1/chat/completions")
def fixture_completion(body: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"capabilities":["chat"],"model_class":"local",'
                        '"reason":"fixture","answer":"4"}'
                    )
                }
            }
        ]
    }


@app.get("/search")
def fixture_search(q: str, format: str = "json") -> dict[str, object]:
    return {
        "results": [
            {
                "url": "https://example.org/synthetic-source",
                "title": "Synthetic public source",
                "content": "SYNTHETIC_WEB_EVIDENCE",
            }
        ]
    }


# Isolated browser fixture: no real Home-Assistant transport or credentials.


def synthetic_ha_inspect(cfg: Settings) -> dict:
    return {
        "label": "LOCAL_ONLY",
        "checked_at": 1791201000,
        "version": "2026.9.3",
        "installation_type": None,
        "supervisor_present": True,
        "backup_integration_present": True,
        "restore_verified": False,
        "writes_enabled": False,
        "available_updates": 1,
        "unavailable_updates": 0,
        "updates": [
            {
                "entity_id": "update.synthetic_core",
                "name": "Synthetisches Core-Update",
                "state": "on",
                "installed_version": "2026.9.3",
                "latest_version": "2026.10.1",
            }
        ],
    }


fixture_action_api.inspect_ha = synthetic_ha_inspect


@app.post("/mcp")
def fixture_mcp(body: dict) -> dict:
    if body["method"] == "tools/call":
        assert body["params"]["name"] == "synthetic.read" and body["params"]["arguments"] == {}
        return {
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "resultType": "complete",
                "content": [{"type": "text", "text": "SYNTHETIC_MCP_READ_RESULT"}],
            },
        }
    assert body["method"] == "tools/list"
    return {
        "jsonrpc": "2.0",
        "id": body["id"],
        "result": {
            "resultType": "complete",
            "tools": [
                {
                    "name": "synthetic.read",
                    "description": "Synthetisches freigegebenes Lesewerkzeug",
                    "inputSchema": {"type": "object", "additionalProperties": False},
                }
            ],
        },
    }


def synthetic_ha_backups(cfg: Settings) -> dict:
    return {
        "label": "LOCAL_ONLY",
        "checked_at": 1791201000,
        "operating_system": "Synthetic HA OS",
        "core_version": "2026.9.3",
        "supervisor_version": "2026.09.3",
        "supervisor_healthy": True,
        "supervisor_supported": True,
        "backup_state": "idle",
        "last_completed_automatic_backup": 1791200000,
        "backup_count": 1,
        "agent_error_count": 0,
        "backups": [
            {
                "id": "synthetic-backup",
                "created": 1791200000,
                "homeassistant_included": True,
                "database_included": True,
                "homeassistant_version": "2026.9.3",
                "copies": [{"protected": True, "size": 123456}],
                "failure_count": 0,
            }
        ],
        "restore_verified": False,
        "writes_enabled": False,
        "archive_integrity_verified": False,
        "recovery_key_verified": False,
        "scope": "installation_and_backup_metadata_only",
    }


fixture_action_api.inspect_ha_backups = synthetic_ha_backups


# Synthetic renderer response only; actual Chromium isolation is tested separately.
def synthetic_browser_snapshot(cfg: Settings, action_id: str, params: dict) -> dict:
    row = fixture_browser.approved(cfg, params["target_id"], params["target_sha256"])
    return {
        "name": row["name"],
        "text": "SYNTHETIC_BROWSER_PAGE_RESULT",
        "png": (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
            "QVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII="
        ),
        "label": "LOCAL_ONLY",
        "url": row["url"],
        "automatic_model_context": False,
        "untrusted": True,
        "live_interaction": False,
    }


fixture_browser.snapshot = synthetic_browser_snapshot
fixture_maintenance.state_inspect = synthetic_ha_inspect
fixture_maintenance.backup_inspect = synthetic_ha_backups

fixture_chat_tools.maintenance = fixture_maintenance.inspect
