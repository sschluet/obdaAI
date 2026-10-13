import asyncio
import json

import httpx
import pytest
from hub.config import Settings
from hub.policy import ContextPart
from hub.providers import Providers


@pytest.mark.parametrize("outer_deadline", [False, True])
def test_router_full_json_has_preparation_read_budget(monkeypatch, outer_deadline):
    original = httpx.AsyncClient
    seen = []

    async def handler(request):
        limits = request.extensions["timeout"]
        seen.append(limits)
        assert limits == {"connect": 1, "write": 1, "pool": 1, "read": 9}
        # Compress the configured seconds for an isolated transport test. The
        # JSON arrives beyond the old idle limit, within the new read budget.
        try:
            await asyncio.wait_for(asyncio.sleep(0.06), timeout=limits["read"] / 100)
        except TimeoutError:
            raise httpx.ReadTimeout("Synthetic idle timeout") from None
        value = json.dumps(
            {
                "capabilities": ["chat"],
                "model_class": "local",
                "reason": "Synthetic preparation",
                "answer": "Synthetic answer",
            }
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": value}}]})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    provider = Providers(Settings(local_model="synthetic-model", local_timeout=1, run_timeout=9))
    monkeypatch.setattr(
        provider, "_target", lambda external: ("http://127.0.0.1/v1/chat/completions", {}, {}, "")
    )

    async def route():
        async with asyncio.timeout(0.03 if outer_deadline else 0.2):
            return await provider.route(
                [ContextPart(content="Synthetic question", source_id="fixture", revision=1)],
                ["user"],
            )

    if outer_deadline:
        with pytest.raises(TimeoutError):
            asyncio.run(route())
    else:
        assert asyncio.run(route()).answer is None
    assert len(seen) == 1 and provider.route_calls == 1


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
    assert asyncio.run(p.route([part], ["user"])).answer is None
    assert all(r["enable_thinking"] is False for r in requests)
    assert all(r["max_tokens"] == 512 for r in requests)
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
def test_empty_stream_limit_and_filter_have_distinct_messages(monkeypatch, reason):
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
        message = "Antwortlimit" if reason == "length" else "Inhaltsfilter"
        with pytest.raises(ExecutionLimitError, match=message):
            async for _ in provider.stream(
                [ContextPart(content="fixture", source_id="x", revision=1)],
                ["user"],
                external=False,
                grants=[],
            ):
                pass

    asyncio.run(run())


@pytest.mark.parametrize("disable_answer_thinking", [False, True])
def test_router_compacts_only_old_answers_and_stream_keeps_full_context(
    monkeypatch, disable_answer_thinking
):
    original = httpx.AsyncClient
    calls = []
    old_answer = "Historical start. " + "middle evidence " * 700 + " Historical conclusion."
    latest_request = "Explain " + "current request " * 60 + "and create a downloadable PDF file."

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if not body.get("stream"):
            route = json.dumps({
                "capabilities": ["chat", "artifact"],
                "model_class": "local",
                "reason": "file requested",
                "answer": None,
            })
            return httpx.Response(200, json={"choices": [{"message": {"content": route}}]})
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"answer"}}]}\n\ndata: [DONE]\n\n',
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    provider = Providers(
        Settings(local_model="fixture", local_disable_thinking=disable_answer_thinking)
    )
    monkeypatch.setattr(
        provider, "_target", lambda external: ("http://127.0.0.1/v1/chat/completions", {}, {}, "")
    )
    parts = [
        ContextPart(content="Prior user question", source_id="prior", revision=1),
        ContextPart(content=old_answer, source_id="answer", revision=1),
        ContextPart(content=latest_request, source_id="current", revision=1),
    ]
    roles = ["user", "assistant", "user"]

    async def run():
        route = await provider.route(parts, roles)
        assert route.capabilities == ["chat", "artifact"] and route.answer is None
        assert "".join([chunk async for chunk in provider.stream(
            parts, roles, external=False, grants=[]
        )]) == "answer"

    asyncio.run(run())
    router, answer = calls
    assert router["messages"][1]["content"] == parts[0].content
    compact = router["messages"][2]["content"]
    assert len(compact) < 900
    assert compact.startswith(old_answer[:384]) and compact.endswith(old_answer[-384:])
    assert "[Earlier assistant answer shortened for classification]" in compact
    assert router["messages"][3]["content"] == latest_request
    assert router["enable_thinking"] is False and router["max_tokens"] == 512
    assert [message["content"] for message in answer["messages"]] == [p.content for p in parts]
    assert parts[1].content == old_answer and parts[2].content == latest_request
    if disable_answer_thinking:
        assert answer["enable_thinking"] is False
    else:
        assert "enable_thinking" not in answer


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("finish", ["stop", "length", "content_filter"])
def test_final_delta_limit_and_usage_are_distinct(monkeypatch, external, finish):
    from hub.budgets import ExecutionLimitError
    from hub.policy import CloudGrant
    from hub.providers import AnswerLimitReached

    original = httpx.AsyncClient
    calls = []
    frames = [
        {"choices": [{"delta": {"content": "Opening "}}]},
        {"choices": [{"delta": {"content": "final"}, "finish_reason": finish}]},
        {"choices": [], "usage": {"cost": 0.0123}},
    ]
    wire = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames)
    wire += "data: [DONE]\n\n"

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=wire)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw))
    provider = Providers(Settings(local_model="fixture", openrouter_model="fixture"))
    monkeypatch.setattr(provider, "_target", lambda external: (
        "http://127.0.0.1/v1/chat/completions", {}, {}, ""))
    chunks = []

    async def collect():
        async for chunk in provider.stream(
            [ContextPart(content="Synthetic", label="CLOUD_ALLOWED", source_id="x", revision=1)],
            ["user"], external=external,
            grants=[CloudGrant(source_id="x", revision=1, provider_id="openrouter")],
        ):
            chunks.append(chunk)

    if finish == "stop":
        asyncio.run(collect())
    else:
        with pytest.raises(AnswerLimitReached if finish == "length" else ExecutionLimitError):
            asyncio.run(collect())
    assert "".join(chunks) == ("Opening " if finish == "content_filter" else "Opening final")
    assert len(calls) == 1
    if external and finish != "content_filter":
        assert provider.measured_cost == 0.0123 and provider.cost_basis == "provider_reported"
