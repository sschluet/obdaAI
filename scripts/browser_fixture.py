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
import hub.ha_backups as fixture_ha_backups
import hub.ha_maintenance as fixture_maintenance
import hub.home_assistant as fixture_ha
import hub.knowledge_api as fixture_knowledge_api
import hub.knowledge_connections as fixture_knowledge_connections
import hub.websearch as fixture_web_pages
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.db import Artifact, ArtifactRevision, Source, SourceChunk
from hub.knowledge_clients import Document
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

# These two blank/binary UI fixtures intentionally do not test OCR. Real parsing
# is exercised by integration tests and the separate production synthetic smoke.
_extract_source = fixture_knowledge_api.extract_source


async def synthetic_media_parse(factory, cfg, source_id):
    with factory() as db:
        row = db.get(Source, source_id)
        if row and row.name in {"synthetic-artifact.pdf", "synthetic-artifact.png"}:
            row.status = "ready"
            if not db.query(SourceChunk).filter_by(source_id=source_id).first():
                db.add(
                    SourceChunk(
                        source_id=source_id,
                        locator="PDF Seite 2" if row.name.endswith(".pdf") else "Bild",
                        content="Synthetic media fixture only",
                    )
                )
            db.commit()
            return
    await _extract_source(factory, cfg, source_id)


fixture_knowledge_api.extract_source = synthetic_media_parse


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
        if spec.plan.kind == "pdf" and spec.plan.sections:
            import hub.artifact_preview as fixture_preview
            from pypdf import PdfWriter

            def synthetic_pdf(path, folder):
                writer = PdfWriter()
                writer.add_blank_page(width=300, height=400)
                target = folder / "artifact.pdf"
                writer.write(target)
                return target

            fixture_preview.office_pdf = synthetic_pdf
        manifest = render(
            spec,
            [
                request / ("source-" + str(i))
                for i in range(len(spec.sources) + bool(spec.template))
            ],
            output / "version",
        )
        manifest["spec_sha256"] = row.spec_sha256
        manifest["status"] = "needs_review"
        previews = output / "version/previews"
        previews.mkdir()
        count = (
            len(spec.plan.slides)
            if spec.plan.kind == "pptx"
            else (len(spec.plan.pages) if spec.plan.kind == "pdf" and spec.plan.pages else 1)
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
        if spec.plan.kind == "docx" and spec.plan.pdf_export:
            from pypdf import PdfWriter

            target = previews / "artifact.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=400)
            writer.write(target)
            manifest["pdf_export"] = {
                "filename": "previews/artifact.pdf",
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "bytes": target.stat().st_size,
            }
        (output / "manifest.json").write_text(json.dumps(manifest))
        reconcile(db, cfg, row)
        db.commit()


fixture_artifact_api.execute_artifact = synthetic_artifact


class SyntheticProvider:
    async def title(self, parts: list[ContextPart], roles: list[str]) -> str:
        await asyncio.sleep(2)
        return "Synthetic automatic title"

    async def route(self, parts: list[ContextPart], roles: list[str]) -> Route:
        if any("SYNTHETIC_LONG_STREAM_RESPONSE" in p.content for p in parts):
            return Route(
                capabilities=["chat"], model_class="local", reason="synthetic delayed stream"
            )
        if any("SYNTHETIC_ANSWER_FILE_REQUEST" in p.content for p in parts):
            return Route(
                capabilities=["artifact"], model_class="local", reason="synthetic answer file"
            )
        if any("SYNTHETIC_FILE_REQUEST" in p.content for p in parts):
            return Route(
                capabilities=["artifact", "web"]
                if any("SYNTHETIC_WEB_QUERY" in p.content for p in parts)
                else ["artifact"],
                model_class="cloud",
                reason="synthetic file",
            )
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
        if any("SYNTHETIC_LONG_STREAM_RESPONSE" in p.content for p in parts):
            assert not external and not grants
            for index in range(48):
                yield (
                    f"\n\n### Synthetischer Abschnitt {index + 1}\n\n"
                    "Dieser isolierte Testtext prüft das Lesen einer langen Antwort während "
                    "der Erzeugung. Die Ansicht soll an der gewählten Leseposition bleiben. "
                    "Weitere Absätze kommen zeitversetzt über den echten Ereignisstrom.\n"
                )
                await asyncio.sleep(0.3)
            return
        if parts and parts[0].source_id == "artifact-draft-policy":
            assert not external and not grants
            if '"tiles"' in parts[0].content:
                yield json.dumps(
                    {
                        "title": "Synthetic local image operation",
                        "tiles": [{"source": 0, "crop": [0.5, 0, 1, 1]}],
                        "columns": 1,
                        "tile_width": 128,
                        "tile_height": 128,
                        "format": "png",
                    }
                )
            elif '"pages"' in parts[0].content:
                yield json.dumps(
                    {
                        "title": "Synthetic local PDF operation",
                        "pages": [{"source": 0, "page": 2, "rotation": 90}],
                    }
                )
            elif '"sheets"' in parts[0].content:
                yield json.dumps(
                    {
                        "title": "Synthetic local spreadsheet",
                        "sheets": [
                            {
                                "name": "Overview",
                                "columns": ["Item", "Value"],
                                "rows": [["Synthetic", 42], ["Reviewed", True]],
                            }
                        ],
                    }
                )
            elif '"slides"' in parts[0].content:
                import re

                count = int(re.search(r"Exactly ([0-9]+) slides", parts[0].content)[1])
                yield json.dumps(
                    {
                        "title": "Synthetic local presentation draft",
                        "slides": [
                            {
                                "title": "Slide " + str(i + 1),
                                "bullets": ["Editable synthetic bullet"],
                                "notes": "Synthetic note",
                            }
                            for i in range(count)
                        ],
                    }
                )
            else:
                yield json.dumps(
                    {
                        "title": "Synthetic local document draft",
                        **(
                            {
                                "letter": {
                                    "recipient": [
                                        "Synthetic recipient",
                                        "Example street 1",
                                        "12345 Example city",
                                    ],
                                    "sender": ["Synthetic sender"],
                                    "subject": "Synthetic letter",
                                    "date": "2026-10-12",
                                    "salutation": "Guten Tag,",
                                    "signature": ["Synthetic sender"],
                                }
                            }
                            if '"letter"' in parts[0].content
                            else {}
                        ),
                        "sections": [
                            {
                                "heading": "Draft result",
                                "paragraphs": ["Editable synthetic draft text."],
                                "table": [["Column A", "Column B"], ["Synthetic", "42"]],
                            }
                        ],
                    }
                )
            return
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


@app.post("/v1/chat/completions", response_model=None)
def fixture_completion(body: dict[str, object]) -> dict[str, object] | StreamingResponse:
    if body.get("stream"):
        messages = body.get("messages")
        if not isinstance(messages, list) or not any(
            isinstance(message, dict)
            and message.get("role") == "user"
            and message.get("content") == "What is 2 plus 2? Answer with the number only."
            for message in messages
        ):
            raise HTTPException(400, "Synthetic endpoint only supports the bounded model probe")
        return StreamingResponse(
            iter(
                [
                    'data: {"choices":[{"delta":{"content":"4"}}]}\n\n',
                    "data: [DONE]\n\n",
                ]
            ),
            media_type="text/event-stream",
        )
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"capabilities":["chat"],"model_class":"local",'
                        '"reason":"fixture","answer":null}'
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
fixture_ha.inspect = synthetic_ha_inspect


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
fixture_ha_backups.inspect = synthetic_ha_backups


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


# These are UI-only source adapters, never a real network-source acceptance.


def synthetic_knowledge_documents(body, password, *, probe=False):
    yield Document(
        "synthetic-knowledge.txt",
        b"Browser citation fact: synthetic external knowledge blue and seven.",
    )


async def synthetic_public_page(cfg, url, approved, *, user_selected=False):
    assert approved and user_selected and url.startswith("https://example.org/")
    return "Browser citation fact: synthetic public website blue and seven."


fixture_knowledge_connections.documents = synthetic_knowledge_documents
fixture_web_pages.fetch_page = synthetic_public_page
