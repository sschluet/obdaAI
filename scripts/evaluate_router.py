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
        parts = [
            ContextPart(
                content=str(case["prompt"]),
                source_id=str(case["id"]),
                revision=1,
                label=Privacy.LOCAL_ONLY,
            )
        ]
        try:
            decision = await provider.route(parts, ["user"])
            expected = set(case["capabilities"])
            passed = expected.issubset(set(decision.capabilities))
            if case.get("simple"):
                passed = passed and decision.model_class == "local" and bool(decision.answer)
            results.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "capabilities": decision.capabilities,
                    "model_class": decision.model_class,
                    "inline_answer": bool(decision.answer),
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
