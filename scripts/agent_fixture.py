"""Isolated synthetic agent UX; never import into a real deployment."""

import json
import os
from typing import Any

from hub import agent_runtime
from hub.agent_context import pointer

from scripts.browser_fixture import app

object.__setattr__(app.state.settings, "integration_targets_enabled", True)
state = {"id": 1, "title": "Synthetisches Dokument"}
original_stream = app.state.providers.stream


async def stream(parts, roles, *, external, grants):
    if parts and parts[0].source_id == "agent-policy":
        assert not external and not grants
        data = json.loads(parts[1].content)
        if "current_user_request" in data:
            yield json.dumps({"queries": []})
            return
        history = data["history"]
        inputs = [s for s in history if s["kind"] == "input"]
        title = inputs[-1]["document"]["content"] if inputs else "Agentenabnahme"
        interface = data["interfaces"][0]
        if "Frage zuerst" in data["goal"] and not inputs:
            output = {
                "kind": "ask",
                "message": "Welchen Titel soll das synthetische Dokument erhalten?",
            }
        elif not any(s["kind"] == "read" for s in history):
            output = {
                "kind": "tool",
                "message": "Dokument und API-Möglichkeiten lesen",
                "integration_id": interface["integration_id"],
                "tool": "http",
                "arguments": {"path": "/api/documents/1/"},
            }
        elif not any(s["kind"] == "effect" for s in history):
            output = {
                "kind": "tool",
                "message": "Synthetisches Dokument umbenennen",
                "integration_id": interface["integration_id"],
                "tool": "http",
                "arguments": {
                    "method": "PATCH",
                    "path": "/api/documents/1/",
                    "body": {
                        "title": "synthetic-lost-response"
                        if "Antwortverlust" in data["goal"]
                        else title
                    },
                },
            }
        elif not any(s["document"].get("tool") == "http.verify" for s in history):
            effect = next(s for s in history if s["kind"] == "effect")
            output = {
                "kind": "tool",
                "message": "Gespeicherten Titel unabhängig prüfen",
                "integration_id": interface["integration_id"],
                "tool": "http.verify",
                "arguments": {
                    "path": "/api/documents/1/",
                    "effect_step": effect["sequence"],
                    "expected": {"/body/title": title},
                },
            }
        else:
            output = {
                "kind": "finish",
                "message": "Das synthetische Dokument wurde umbenannt "
                "und der gespeicherte Titel erneut geprüft.",
            }
        yield json.dumps(output)
        return
    async for text in original_stream(parts, roles, external=external, grants=grants):
        yield text


def invoke(cfg, config, secret, tool, args, rules, before_send) -> dict[str, Any]:
    if config["url"] != "https://agent.example.test" or tool not in {"http", "http.verify"}:
        raise ValueError("Only isolated synthetic agent targets supported")
    before_send()
    if args["method"] == "PATCH":
        state["title"] = args["body"]["title"]
        if state["title"] == "synthetic-lost-response":
            raise TimeoutError("Synthetic lost response")
    result = {"body": dict(state), "http_status": 200, "effect_verified": False}
    if tool == "http.verify":
        result["verification_passed"] = all(
            pointer(result, p) == value for p, value in args["expected"].items()
        )
    return result


app.state.providers.stream = stream
agent_runtime.invoke = invoke


@app.middleware("http")
async def fixture_marker(request, call_next):
    response = await call_next(request)
    response.headers["X-OBDAAI-SYNTHETIC-FIXTURE"] = os.environ["HUB_AGENT_FIXTURE_ID"]
    return response
