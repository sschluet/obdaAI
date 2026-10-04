import asyncio
import json

import httpx
import pytest
from hub.config import Settings
from hub.policy import ContextPart
from hub.providers import Providers


@pytest.mark.parametrize("disable_thinking", [False, True])
def test_json_router_one_call_and_bounded_repair(
    monkeypatch: pytest.MonkeyPatch, disable_thinking: bool
) -> None:
    original = httpx.AsyncClient
    requests = []
    responses = [
        "invalid",
        json.dumps(
            {
                "capabilities": ["chat"],
                "model_class": "local",
                "source_scopes": [],
                "reason": "fixture",
                "answer": "4",
            }
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": responses.pop(0)}}]})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    p = Providers(Settings(local_model="synthetic-model", local_disable_thinking=disable_thinking))
    monkeypatch.setattr(
        p, "_target", lambda external: ("http://127.0.0.1/v1/chat/completions", {}, {}, "")
    )
    part = ContextPart(content="2+2", source_id="fixture", revision=1)
    assert asyncio.run(p.route([part], ["user"])).answer == "4"
    if disable_thinking:
        assert all(r["enable_thinking"] is False for r in requests)
    else:
        assert all("enable_thinking" not in r for r in requests)
    assert len(requests) == 2
    assert len(requests[1]["messages"]) == len(requests[0]["messages"]) + 2


def test_stream_requires_completion_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    p = Providers(Settings(local_model="synthetic-model"))
    monkeypatch.setattr(
        p, "_target", lambda external: ("http://127.0.0.1/v1/chat/completions", {}, {}, "")
    )

    async def run() -> None:
        with pytest.raises(ValueError, match="completion marker"):
            async for _ in p.stream(
                [ContextPart(content="fixture", source_id="x", revision=1)],
                ["user"],
                external=False,
                grants=[],
            ):
                pass

    asyncio.run(run())
