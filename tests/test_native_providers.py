"""Synthetic HTTP protocol acceptance; no native API key or paid live request."""

import json
from decimal import Decimal

import httpx
import pytest
from hub.native_providers import REVIEWED_AT, NativeConfig, NativeProvider, events, prices
from hub.policy import CloudGrant, ContextPart


@pytest.fixture
def anyio_backend():
    return "asyncio"


def part(label="CLOUD_ALLOWED"):
    return ContextPart(content="Synthetic blue", label=label, source_id="synthetic", revision=1)


def grant(kind):
    return CloudGrant(source_id="synthetic", revision=1, provider_id=kind)


def wire(values):
    return b"".join(b"data: " + json.dumps(v).encode() + b"\n\n" for v in values)


def fixture(monkeypatch, values, status=200):
    requests = []
    original = httpx.AsyncClient

    def response(request):
        requests.append(request)
        return httpx.Response(
            status, content=wire(values), headers={"Content-Type": "text/event-stream"}
        )

    monkeypatch.setattr(
        "hub.providers.socket.getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("1.1.1.1", 443))],
    )
    monkeypatch.setattr(
        "hub.native_providers.httpx.AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(response)),
    )
    monkeypatch.setattr("hub.native_providers.time.time", lambda: REVIEWED_AT + 3600)
    return requests


async def collect(provider, kind, p=None, grants=None):
    return "".join(
        [s async for s in provider.stream([p or part()], ["user"], grants=grants or [grant(kind)])]
    )


@pytest.mark.anyio
async def test_openai_fixed_responses_payload_and_usage_estimate(monkeypatch):
    requests = fixture(
        monkeypatch,
        [
            {"type": "response.output_text.delta", "delta": "Blue"},
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                },
            },
        ],
    )
    provider = NativeProvider(NativeConfig("openai", "gpt-4.1-mini", enabled=True), "synthetic-key")
    assert await collect(provider, "openai") == "Blue"
    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://1.1.1.1/v1/responses"
    assert request.headers["Host"] == "api.openai.com"
    assert request.extensions["sni_hostname"] == "api.openai.com"
    assert body["store"] is False and body["background"] is False
    assert body["service_tier"] == "default" and body["truncation"] == "disabled"
    assert "tools" not in body and "messages" not in body
    assert provider.estimated_cost == Decimal("0.000072")
    assert provider.cost_basis == "usage_estimate"


@pytest.mark.anyio
async def test_anthropic_native_headers_system_and_cumulative_usage(monkeypatch):
    requests = fixture(
        monkeypatch,
        [
            {"type": "message_start", "message": {"usage": {"input_tokens": 100}}},
            {"type": "content_block_start", "content_block": {"type": "text"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Blue"}},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 20},
            },
            {"type": "message_stop"},
        ],
    )
    provider = NativeProvider(
        NativeConfig("anthropic", "claude-haiku-4-5-20251001", enabled=True), "synthetic-key"
    )
    assert await collect(provider, "anthropic") == "Blue"
    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://1.1.1.1/v1/messages"
    assert request.headers["x-api-key"] == "synthetic-key"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in request.headers and "tools" not in body
    assert provider.estimated_cost == Decimal("0.0002")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind,model", [("openai", "gpt-4.1-mini"), ("anthropic", "claude-haiku-4-5-20251001")]
)
async def test_privacy_and_other_provider_grants_fail_before_dns(monkeypatch, kind, model):
    def forbidden(*a, **k):
        pytest.fail("Denied context reached DNS")

    monkeypatch.setattr("hub.providers.socket.getaddrinfo", forbidden)
    provider = NativeProvider(NativeConfig(kind, model, enabled=True), "synthetic-key")
    with pytest.raises(PermissionError):
        await collect(provider, kind, p=part("LOCAL_ONLY"))
    with pytest.raises(PermissionError):
        await collect(provider, kind, grants=[grant("openrouter")])
    with pytest.raises(ValueError, match="enabled"):
        await collect(NativeProvider(NativeConfig(kind, model), "synthetic-key"), kind)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "values",
    [
        [{"type": "response.output_text.delta", "delta": "partial"}],
        [{"type": "error", "error": {"message": "synthetic"}}],
        [{"type": "response.incomplete"}],
        [{"type": "response.output_item.added", "item": {"type": "function_call"}}],
        [
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "usage": {"input_tokens": True, "output_tokens": 10},
                },
            }
        ],
    ],
)
async def test_error_truncation_tools_and_invalid_usage_fail(monkeypatch, values):
    requests = fixture(monkeypatch, values)
    provider = NativeProvider(NativeConfig("openai", "gpt-4.1-mini", enabled=True), "synthetic-key")
    with pytest.raises(ValueError):
        await collect(provider, "openai")
    assert len(requests) == 1 and provider.estimated_cost is None


@pytest.mark.anyio
async def test_missing_usage_does_not_claim_zero_cost(monkeypatch):
    fixture(
        monkeypatch,
        [
            {"type": "response.output_text.delta", "delta": "Blue"},
            {"type": "response.completed", "response": {"status": "completed"}},
        ],
    )
    provider = NativeProvider(NativeConfig("openai", "gpt-4.1-mini", enabled=True), "synthetic-key")
    await collect(provider, "openai")
    assert provider.estimated_cost is None and provider.cost_basis == "unknown"


def test_unknown_and_stale_prices_fail_closed():
    with pytest.raises(ValueError):
        prices("openai", "unpriced-model", now=REVIEWED_AT)
    with pytest.raises(ValueError):
        prices("openai", "gpt-4.1-mini", now=REVIEWED_AT + 8 * 86400)


@pytest.mark.anyio
async def test_frame_size_and_truncated_frame_limits():
    for content in (b"data: " + b"x" * 70000 + b"\n\n", b'data: {"type":"ping"}'):
        with pytest.raises(ValueError):
            [value async for value in events(httpx.Response(200, content=content))]
