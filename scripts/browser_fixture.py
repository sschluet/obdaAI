"""Synthetic test server; never a deployment configuration or live model test."""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from hub.api import create_app
from hub.auth import password_hash
from hub.config import Settings
from hub.policy import CloudGrant, ContextPart
from hub.routing import Route

folder = Path(".local/browser")
folder.mkdir(parents=True, exist_ok=True)
os.environ["HUB_DATABASE_URL"] = "sqlite:///" + str(folder / "fixture.sqlite")
command.upgrade(Config("alembic.ini"), "head")
app = create_app(
    Settings(
        database_url=os.environ["HUB_DATABASE_URL"],
        origin=os.getenv("HUB_BROWSER_ORIGIN", "http://127.0.0.1:18765"),
        secure_cookie=False,
        password_hash=password_hash("synthetic-ui-password"),
    )
)


class SyntheticProvider:
    async def route(self, parts: list[ContextPart], roles: list[str]) -> Route:
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
        raise RuntimeError("Simple synthetic fixture must not make a second model call")
        yield ""


app.state.providers = SyntheticProvider()
