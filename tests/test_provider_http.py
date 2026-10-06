import asyncio
import json

import httpx
import pytest
from hub.config import Settings
from hub.policy import ContextPart
from hub.providers import Providers


@pytest.mark.parametrize(
    "prefix", ["QUELLE [file]", "VAULT file", "WEBQUELLE https://example.org/"]
)
def test_source_text_is_classified_as_metadata_but_answer_receives_full_source(monkeypatch, prefix):
    original = httpx.AsyncClient
    requests = []
    marker = "SYNTHETIC_UNTRUSTED_SOURCE_INSTRUCTIONS"

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if not body.get("stream"):
            value = json.dumps(
                {
                    "capabilities": ["chat"],
                    "model_class": "local",
                    "reason": "synthetic",
                    "answer": "unsubstantiated shortcut",
                }
            )
            return httpx.Response(200, json={"choices": [{"message": {"content": value}}]})
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"source answer"}}]}\n\ndata: [DONE]\n\n',
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    provider = Providers(Settings(local_model="fixture"))
    monkeypatch.setattr(
        provider, "_target", lambda external: ("http://127.0.0.1/v1/chat/completions", {}, {}, "")
    )
    parts = [
        ContextPart(content="Summarize my stored source", source_id="question", revision=1),
        ContextPart(content=prefix + "\n" + marker, source_id="source", revision=2),
    ]

    async def run():
        route = await provider.route(parts, ["user", "user"])
        assert route.answer is None and "retrieval" in route.capabilities
        answer = ""
        async for chunk in provider.stream(parts, ["user", "user"], external=False, grants=[]):
            answer += chunk
        assert answer == "source answer"

    asyncio.run(run())
    assert marker not in json.dumps(requests[0])
    assert marker in json.dumps(requests[1])


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
    assert len(requests) == 2 and p.route_calls == 2
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


@pytest.mark.parametrize(
    "content",
    [
        '{"title":"Synthetic title"}',
        '{"title":""}',
        '{"title":"bad\\nline"}',
        '{"title":"x","extra":true}',
        '{"title":42}',
        "not json",
    ],
)
def test_title_is_local_and_rejects_invalid_derivatives(monkeypatch, content):
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    provider = Providers(
        Settings(local_model="local-fixture", cloud_enabled=True, local_disable_thinking=True)
    )

    def target(external):
        assert external is False
        return "http://127.0.0.1/v1/chat/completions", {}, {}, ""

    monkeypatch.setattr(provider, "_target", target)
    part = ContextPart(content="synthetic private context", source_id="title-source", revision=1)
    if content == '{"title":"Synthetic title"}':
        assert asyncio.run(provider.title([part], ["user"])) == "Synthetic title"
    else:
        with pytest.raises(ValueError):
            asyncio.run(provider.title([part], ["user"]))
    assert len(calls) == 1
    assert calls[0]["model"] == "local-fixture" and calls[0]["enable_thinking"] is False


@pytest.mark.parametrize("reason", ["length", "content_filter"])
def test_stream_truncation_is_explicit_failure(monkeypatch, reason):
    from hub.budgets import ExecutionLimitError

    original = httpx.AsyncClient

    def handler(request):
        return httpx.Response(
            200,
            text="data: "
            + json.dumps({"choices": [{"delta": {}, "finish_reason": reason}]})
            + "\n\ndata: [DONE]\n\n",
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    provider = Providers(Settings(local_model="fixture"))
    monkeypatch.setattr(
        provider, "_target", lambda external: ("http://127.0.0.1/v1/chat/completions", {}, {}, "")
    )

    async def run():
        with pytest.raises(ExecutionLimitError, match="Tokenlimit"):
            async for _ in provider.stream(
                [ContextPart(content="fixture", source_id="x", revision=1)],
                ["user"],
                external=False,
                grants=[],
            ):
                pass

    asyncio.run(run())
