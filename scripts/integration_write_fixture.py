"""Isolated synthetic write UI fixture. Never use as an application deployment."""

import hashlib
import os
from typing import Any

from hub import integration_write_adapters as adapters
from hub.config import Settings

from scripts.browser_fixture import app

object.__setattr__(app.state.settings, "integration_targets_enabled", True)
states: dict[str, dict[str, Any]] = {}


def snapshot(
    cfg: Settings, config: dict[str, Any], secret: str, operation: str, args: dict[str, Any]
) -> dict[str, Any]:
    if config["url"] != "synthetic-write.example.test" or operation != "file.write_text":
        raise ValueError("Only isolated synthetic write targets are supported")
    return states.get(args["filename"], {"exists": False, "sha256": None}).copy()


def apply(
    cfg: Settings,
    config: dict[str, Any],
    secret: str,
    operation: str,
    args: dict[str, Any],
    request_id: str,
    before_send: Any = None,
) -> None:
    snapshot(cfg, config, secret, operation, args)
    if before_send:
        before_send()
    states[args["filename"]] = {
        "exists": True,
        "sha256": hashlib.sha256(args["content"].encode()).hexdigest(),
    }
    if args["content"] == "synthetic-lost-response":
        raise TimeoutError("Synthetic response lost after effect")


adapters.snapshot = snapshot
adapters.apply = apply


original_stream = app.state.providers.stream


async def draft_stream(parts, roles, *, external, grants):
    import json

    if parts and parts[0].source_id == "integration-write-policy":
        assert not external and not grants
        yield json.dumps(
            {
                "message": "Bitte den lokalen Vorschlag prüfen.",
                "arguments": {"filename": "ai-example.txt", "content": "Synthetischer KI-Entwurf"},
            }
        )
        return
    async for chunk in original_stream(parts, roles, external=external, grants=grants):
        yield chunk


app.state.providers.stream = draft_stream


@app.get("/api/synthetic-write-fixture-id")
def fixture_id():
    return {"fixture_id": os.getenv("HUB_WRITE_FIXTURE_ID", "manual-synthetic-fixture")}
