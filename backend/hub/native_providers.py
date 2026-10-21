"""Fixed native text APIs; explicit provider grants precede DNS and payload creation.

Not selected by the router yet. Server opt-in, a key, exact provider consent and
reviewed pricing are required even for this independent transport boundary.
"""

import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import httpx

from hub.budgets import ExecutionLimitError
from hub.policy import CloudGrant, ContextPart, check_egress
from hub.providers import AnswerLimitReached, pinned_url

NativeKind = Literal["openai", "anthropic"]
ENDPOINTS = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1"}
# Published standard input/output USD per million tokens, reviewed 2026-10-05.
# Explicitly estimates, never provider invoice amounts. Unknown/stale prices fail closed.
REVIEWED_AT = 1791158400  # 2026-10-05 00:00 UTC
RATES = {
    ("openai", "gpt-4.1-mini"): (Decimal("0.40"), Decimal("1.60")),
    ("openai", "gpt-4.1-mini-2025-04-14"): (Decimal("0.40"), Decimal("1.60")),
    ("anthropic", "claude-haiku-4-5-20251001"): (Decimal("1"), Decimal("5")),
}
PRICE_SOURCES = {
    "openai": "https://developers.openai.com/api/docs/models/gpt-4.1-mini",
    "anthropic": "https://platform.claude.com/docs/en/models/haiku-4-5/overview",
}


def prices(kind: NativeKind, model: str, *, now: float | None = None) -> tuple[Decimal, Decimal]:
    stamp = time.time() if now is None else now
    if not REVIEWED_AT <= stamp <= REVIEWED_AT + 7 * 86400:
        raise ValueError("Native provider prices require a new reviewed snapshot")
    try:
        return RATES[(kind, model)]
    except KeyError:
        raise ValueError("Model has no reviewed native provider prices") from None


def tokens(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2_000_000:
        raise ValueError("Invalid native token usage")
    return value


async def events(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Bound individual SSE frames and the whole stream before JSON parsing."""
    pending = b""
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > 2 * 1024 * 1024 or len(chunk) > 256 * 1024:
            raise ValueError("Native stream exceeds byte limit")
        pending = (pending + chunk).replace(b"\r\n", b"\n")
        while b"\n\n" in pending:
            frame, pending = pending.split(b"\n\n", 1)
            if len(frame) > 65536:
                raise ValueError("Native SSE frame exceeds limit")
            payload = b"\n".join(
                line[5:].lstrip() for line in frame.splitlines() if line.startswith(b"data:")
            )
            if not payload:
                continue
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError("Invalid native SSE object")
            yield data
        if len(pending) > 65536:
            raise ValueError("Native SSE frame exceeds limit")
    if pending.strip():
        raise ValueError("Native SSE ended with an incomplete frame")


@dataclass(frozen=True)
class NativeConfig:
    kind: NativeKind
    model: str
    enabled: bool = False
    output_tokens: int = 2048
    timeout: int = 30

    def validate(self) -> None:
        if self.kind not in ENDPOINTS or not self.model or not 16 <= self.output_tokens <= 8192:
            raise ValueError("Invalid native provider configuration")
        if not 5 <= self.timeout <= 60:
            raise ValueError("Invalid native timeout")


class NativeProvider:
    def __init__(self, cfg: NativeConfig, key: str):
        cfg.validate()
        self.cfg, self.key = cfg, key
        self.estimated_cost: Decimal | None = None
        self.usage: dict[str, int] | None = None
        self.cost_basis = "unknown"
        self.before_send: Callable[[], None] | None = None

    async def stream(
        self, parts: list[ContextPart], roles: list[str], *, grants: list[CloudGrant]
    ) -> AsyncIterator[str]:
        cfg = self.cfg
        self.estimated_cost, self.usage, self.cost_basis = None, None, "unknown"
        # A permission for OpenRouter never authorizes either direct provider.
        check_egress(parts, external=True, provider_id=cfg.kind, grants=grants)
        if not cfg.enabled or not self.key or len(self.key) > 4096:
            raise ValueError("Native provider is not enabled/configured")
        rate = prices(cfg.kind, cfg.model)
        if len(parts) != len(roles) or not parts or len(parts) > 100:
            raise ValueError("Invalid native context")
        if any(role not in ("system", "user", "assistant") for role in roles):
            raise ValueError("Native text-only roles required")
        if sum(len(p.content.encode()) for p in parts) > 24000:
            raise ValueError("Native context exceeds byte limit")
        target, headers, extensions = pinned_url(
            ENDPOINTS[cfg.kind],
            "/responses" if cfg.kind == "openai" else "/messages",
            external=True,
        )
        messages = [
            {"role": role, "content": p.content} for role, p in zip(roles, parts, strict=True)
        ]
        body: dict[str, Any] = {"model": cfg.model, "stream": True}
        if cfg.kind == "openai":
            headers["Authorization"] = "Bearer " + self.key
            body.update(
                input=messages,
                max_output_tokens=cfg.output_tokens,
                store=False,
                background=False,
                service_tier="default",
                truncation="disabled",
            )
        else:
            headers.update({"x-api-key": self.key, "anthropic-version": "2023-06-01"})
            body.update(
                max_tokens=cfg.output_tokens,
                messages=[m for m in messages if m["role"] != "system"],
            )
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            if system:
                body["system"] = system
            if not body["messages"] or body["messages"][0]["role"] != "user":
                raise ValueError("Anthropic requires an initial user message")
        count, input_count, output_count = 0, None, None
        termination: ExecutionLimitError | None = None
        async with httpx.AsyncClient(
            timeout=cfg.timeout, trust_env=False, follow_redirects=False
        ) as client:
            if self.before_send:
                self.before_send()
            async with client.stream(
                "POST", target, headers=headers, extensions=extensions, json=body
            ) as response:
                response.raise_for_status()
                async for event in events(response):
                    typ = event.get("type", "")
                    chunk = None
                    done = False
                    if typ in ("error", "response.failed"):
                        raise ValueError("Native provider returned an unsuccessful response")
                    if cfg.kind == "openai":
                        if typ == "response.output_text.delta":
                            chunk = event.get("delta")
                        elif typ == "response.output_item.added":
                            if event.get("item", {}).get("type") != "message":
                                raise ValueError("Native tools are not enabled")
                        elif typ in ("response.completed", "response.incomplete"):
                            value = event.get("response", {})
                            reason = (value.get("incomplete_details") or {}).get("reason")
                            if typ == "response.incomplete" and reason == "max_output_tokens":
                                termination = AnswerLimitReached()
                            elif typ == "response.incomplete" and reason == "content_filter":
                                termination = ExecutionLimitError(
                                    "Antwort durch den Inhaltsfilter des Providers beendet"
                                )
                            elif value.get("status") != "completed":
                                raise ValueError("Native response did not complete")
                            usage = value.get("usage")
                            if usage is not None:
                                input_count = tokens(usage.get("input_tokens"))
                                output_count = tokens(usage.get("output_tokens"))
                            done = True
                    else:
                        if typ == "message_start":
                            usage = event.get("message", {}).get("usage")
                            if usage is not None:
                                input_count = tokens(usage.get("input_tokens")) + tokens(
                                    usage.get("cache_read_input_tokens", 0)
                                )
                                if tokens(usage.get("cache_creation_input_tokens", 0)):
                                    raise ValueError("Unexpected charged prompt cache creation")
                        elif typ == "content_block_start":
                            if event.get("content_block", {}).get("type") != "text":
                                raise ValueError("Native tools are not enabled")
                        elif typ == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") != "text_delta":
                                raise ValueError("Unsupported native content block")
                            chunk = delta.get("text")
                        elif typ == "message_delta":
                            stop_reason = event.get("delta", {}).get("stop_reason")
                            if stop_reason == "max_tokens":
                                termination = AnswerLimitReached()
                            elif stop_reason == "refusal":
                                termination = ExecutionLimitError(
                                    "Antwort durch den Inhaltsfilter des Providers beendet"
                                )
                            elif stop_reason not in (None, "end_turn"):
                                raise ValueError("Native answer stopped before completion")
                            usage = event.get("usage")
                            if usage is not None:
                                output_count = tokens(usage.get("output_tokens"))
                        elif typ == "message_stop":
                            done = True
                    if chunk is not None:
                        if not isinstance(chunk, str):
                            raise ValueError("Invalid native text delta")
                        count += len(chunk.encode())
                        if count > 64000:
                            raise ValueError("Native output exceeds byte limit")
                        yield chunk
                    if done:
                        if not count and termination is None:
                            raise ValueError("Native provider returned no text")
                        if input_count is not None and output_count is not None:
                            if output_count > cfg.output_tokens:
                                raise ValueError("Native provider exceeded output cap")
                            self.usage = {
                                "input_tokens": input_count,
                                "output_tokens": output_count,
                            }
                            self.estimated_cost = (
                                rate[0] * input_count + rate[1] * output_count
                            ) / Decimal(1000000)
                            self.cost_basis = "usage_estimate"
                        if termination:
                            raise termination
                        return
                raise ValueError("Native stream ended without completion marker")
