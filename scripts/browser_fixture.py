"""Synthetic test server; never a deployment configuration or live model test."""

import asyncio
import base64
import os
from collections.abc import AsyncIterator
from pathlib import Path

import hub.action_api as fixture_action_api
from alembic import command
from alembic.config import Config
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.policy import CloudGrant, ContextPart
from hub.routing import Route

folder = Path(".local/browser")
folder.mkdir(parents=True, exist_ok=True)
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
        origin=os.getenv("HUB_BROWSER_ORIGIN", "http://127.0.0.1:18765"),
        secure_cookie=False,
        password_hash=password_hash("synthetic-ui-password"),
        secrets_key_file=str(key_file),
        ha_token_file="synthetic-fixture-only",
        ha_allowed_ip="192.0.2.1",
        source_dir=str(folder / "sources"),
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


class SyntheticProvider:
    async def title(self, parts: list[ContextPart], roles: list[str]) -> str:
        await asyncio.sleep(2)
        return "Synthetic automatic title"

    async def route(self, parts: list[ContextPart], roles: list[str]) -> Route:
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
            yield '{"title":"Synthetischer lokaler Analyseentwurf"}'
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
