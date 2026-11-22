"""Synthetic local router classification evaluation. Never calls an answer provider."""

import argparse
import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from hub.config import Settings
from hub.db import ProviderConfig, session_factory
from hub.policy import ContextPart, Privacy
from hub.provider_api import adapter
from hub.providers import Providers
from sqlalchemy import select
from sqlalchemy.engine import make_url


def local_provider(cfg: Settings) -> Providers:
    """Read configured local adapter without seeding or mutating the runtime DB."""
    url = make_url(cfg.database_url)
    if url.drivername.startswith("sqlite") and url.database not in {None, ":memory:"}:
        if not Path(url.database).is_file():
            raise ValueError("Configured local-provider database is unavailable")
    with session_factory(cfg.database_url)() as db:
        row = db.scalar(
            select(ProviderConfig).where(
                ProviderConfig.kind == "local",
                ProviderConfig.is_default.is_(True),
                ProviderConfig.enabled.is_(True),
            )
        )
        if row:
            provider = adapter(row, cfg)
            provider.settings = replace(
                provider.settings,
                local_max_tokens=min(1024, int(json.loads(row.config)["output_tokens"])),
            )
            return provider
    return Providers(cfg)


async def evaluate(
    cases: list[dict[str, Any]],
    *,
    provider: Any = None,
    cfg: Settings | None = None,
) -> dict[str, Any]:
    provider = provider if provider is not None else local_provider(cfg or Settings.from_env())
    results = []
    for case in cases:
        started = time.monotonic()
        history = case.get("context", [])
        if not isinstance(history, list) or "answer_contains" in case:
            raise ValueError("Router corpus must classify only; answer_contains is obsolete")
        history = history + [{"role": "user", "content": str(case["prompt"])}]
        parts = [
            ContextPart(
                content=m["content"],
                source_id=str(case["id"]) + "-" + str(i),
                revision=1,
                label=Privacy.LOCAL_ONLY,
            )
            for i, m in enumerate(history)
        ]
        roles = [m["role"] for m in history]
        before_calls = provider.route_calls
        try:
            decision = await provider.route(parts, roles)
            observed = set(decision.capabilities)
            expected = set(case["capabilities"])
            passed = expected.issubset(observed) and decision.answer is None
            passed = passed and not (set(case.get("forbidden_capabilities", [])) & observed)
            if case.get("model_class"):
                passed = passed and decision.model_class == case["model_class"]
            if case.get("simple"):
                passed = (
                    passed
                    and decision.model_class == "local"
                    and 1 <= provider.route_calls - before_calls <= 2
                )
            results.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "capabilities": decision.capabilities,
                    "model_class": decision.model_class,
                    "classification_only": decision.answer is None,
                    "router_http_calls": provider.route_calls - before_calls,
                    "seconds": round(time.monotonic() - started, 3),
                }
            )
        except Exception:
            results.append(
                {
                    "id": case["id"],
                    "passed": False,
                    "error": "router_failed",
                    "seconds": round(time.monotonic() - started, 3),
                }
            )
    return {
        "corpus_contract": "classification-only-v2",
        "synthetic": True,
        "local_only": True,
        "answer_provider_calls": 0,
        "cases": results,
        "passed": sum(bool(r["passed"]) for r in results),
        "total": len(results),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(evaluate(json.loads(args.cases.read_text()))), indent=2))
