"""Local-only synthetic router evaluation; no answer-provider calls or customer data."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from hub.config import Settings
from hub.db import session_factory
from hub.policy import ContextPart, Privacy
from hub.provider_settings import runtime_provider


async def evaluate(cases: list[dict[str, object]]) -> dict[str, object]:
    cfg = Settings.from_env()
    _, provider, _ = runtime_provider(session_factory(cfg.database_url), cfg)
    results = []
    for case in cases:
        started = time.monotonic()
        history = case.get("context", [])
        assert isinstance(history, list)
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
            expected = set(case["capabilities"])
            passed = expected.issubset(set(decision.capabilities))
            if case.get("model_class"):
                passed = passed and decision.model_class == case["model_class"]
            if case.get("simple"):
                passed = (
                    passed
                    and decision.model_class == "local"
                    and bool(decision.answer)
                    and provider.route_calls - before_calls == 1
                )
            if case.get("answer_contains"):
                passed = passed and str(case["answer_contains"]) in (decision.answer or "")
            results.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "capabilities": decision.capabilities,
                    "model_class": decision.model_class,
                    "inline_answer": bool(decision.answer),
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
        "synthetic": True,
        "local_only": True,
        "cases": results,
        "passed": sum(bool(r["passed"]) for r in results),
        "total": len(results),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(evaluate(json.loads(args.cases.read_text()))), indent=2))
