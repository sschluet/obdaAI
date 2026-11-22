"""Versioned local semantic-intent evaluation; never dispatches integration tools.

Default is an inert corpus check. --run authorizes local model requests only.
This measures interpretation and contract acceptance, not end-to-end fulfillment.
"""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import statistics
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hub.agent_intent import RequestIntent, accept_semantic, semantic_request
from hub.policy import ContextPart, Privacy

DEFAULT_CORPUS = (
    Path(__file__).resolve().parent.parent / "tests/fixtures/agent-prompt-cases-v2.json"
)


def load_corpus(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if (
        data.get("version") not in {"agent-intent-v1", "agent-intent-v2"}
        or data.get("synthetic") is not True
    ):
        raise ValueError("A versioned synthetic corpus is required")
    ids = [case["id"] for case in data["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Case IDs must be unique")
    for profile in data["profiles"]:
        if (
            set(profile) != {"id", "kind", "name"}
            or not profile["id"].startswith("synthetic-")
            or not profile["name"].startswith("Synthetic ")
        ):
            raise ValueError("Only synthetic profile metadata, never configuration or credentials")
    return data


def semantic_score(intent: RequestIntent, expected: dict[str, Any]) -> list[str]:
    failures = []
    if intent.mode not in expected.get("modes", [intent.mode]):
        failures.append("mode")
    if set(intent.target_ids) != set(expected.get("target_ids", [])):
        failures.append("target_selection")
    if intent.answer_kind not in expected.get("answer_kinds", [intent.answer_kind]):
        failures.append("specialized_answer_scope")
    if intent.confidence not in expected.get("confidence", [intent.confidence]):
        failures.append("confidence")
    for requirement in expected.get("requirements", []):
        if not any(
            all(getattr(item, key) == value for key, value in requirement.items())
            for item in intent.requirements
        ):
            failures.append("missing_evidence_requirement")
    return sorted(set(failures))


async def evaluate(
    corpus: dict[str, Any],
    provider: Any,
    *,
    split: str | None = None,
    case_ids: set[str] | None = None,
    timeout_seconds: float = 45,
) -> dict[str, Any]:
    if hasattr(provider, "settings"):
        provider.settings = replace(
            provider.settings,
            local_max_tokens=min(768, provider.settings.local_max_tokens),
            local_disable_thinking=True,
        )
    profiles = {row["id"]: SimpleNamespace(**row) for row in corpus["profiles"]}
    results = []
    for case in corpus["cases"]:
        if (split and case["split"] != split) or (case_ids and case["id"] not in case_ids):
            continue
        expected = case["expect"]
        if expected.get("contract") == "unknown_target_rejected":
            try:
                accept_semantic(
                    {
                        "mode": "observe",
                        "topic": "general",
                        "answer_kind": "general",
                        "research": False,
                        "followup": False,
                        "freshness": "current",
                        "confidence": "certain",
                        "target_ids": ["synthetic-unavailable"],
                        "requirements": [
                            {
                                "kind": "system",
                                "domain": "",
                                "integration_id": "synthetic-unavailable",
                            }
                        ],
                    },
                    profiles,
                )
            except ValueError:
                passed = True
            else:
                passed = False
            results.append(
                {
                    "id": case["id"],
                    "split": case["split"],
                    "passed": passed,
                    "contract_only": True,
                    "model_calls": 0,
                    "seconds": 0.0,
                }
            )
            continue
        request = semantic_request(case["prompt"], profiles)
        provider.local_json_schema = request["schema"]
        parts = [
            ContextPart(
                content=request["instruction"],
                source_id="synthetic-intent-policy",
                revision=1,
                label=Privacy.LOCAL_ONLY,
            ),
            ContextPart(
                content=json.dumps(request["data"], ensure_ascii=False),
                source_id="synthetic-intent-data",
                revision=1,
                label=Privacy.LOCAL_ONLY,
            ),
        ]
        started = time.monotonic()
        first_token = None
        pieces: list[str] = []
        result: dict[str, Any] = {
            "id": case["id"],
            "split": case["split"],
            "passed": False,
            "contract_only": False,
            "model_calls": 1,
        }
        try:
            async with asyncio.timeout(timeout_seconds):
                async for chunk in provider.stream(
                    parts, ["system", "user"], external=False, grants=[]
                ):
                    if type(chunk) is not str:
                        raise ValueError("Invalid model stream")
                    if chunk and first_token is None:
                        first_token = time.monotonic() - started
                    pieces.append(chunk)
                    if sum(map(len, pieces)) > 16000:
                        raise ValueError("Bounded intent output exceeded")
            payload = json.loads("".join(pieces))
            intent = accept_semantic(payload, profiles)
            failures = semantic_score(intent, expected)
            result.update(
                passed=not failures,
                semantic_failures=failures,
                mode=intent.mode,
                target_ids=intent.target_ids,
                evidence=[item.model_dump() for item in intent.requirements],
            )
        except TimeoutError:
            result["error"] = "model_timeout"
        except (ValueError, TypeError):
            result["error"] = "invalid_intent"
        except Exception:
            result["error"] = "model_unavailable"
        result.update(
            seconds=round(time.monotonic() - started, 4),
            first_token_seconds=round(first_token, 4) if first_token is not None else None,
        )
        results.append(result)
    model_results = [row for row in results if not row["contract_only"]]
    times = sorted(row["seconds"] for row in model_results)
    by_split = {
        name: {
            "passed": sum(bool(r["passed"]) for r in model_results if r["split"] == name),
            "total": sum(r["split"] == name for r in model_results),
        }
        for name in sorted({r["split"] for r in model_results})
    }
    return {
        "corpus_version": corpus["version"],
        "synthetic": True,
        "local_only": True,
        "scope": "semantic_interpretation_only_not_end_to_end",
        "role_budget": {"max_tokens_ceiling": 768, "disable_thinking": True},
        "integration_target_calls": 0,
        "cloud_calls": 0,
        "cases": results,
        "model_cases": len(model_results),
        "passed": sum(bool(row["passed"]) for row in model_results),
        "by_split": by_split,
        "latency_seconds": {
            "median": statistics.median(times) if times else None,
            "p95": times[max(0, math.ceil(len(times) * 0.95) - 1)] if times else None,
        },
    }


def configured_provider() -> Any:
    # Sharing the read-only configured local adapter keeps endpoint/key rules and
    # the application's capacity gate; no evaluation run or chat is stored.
    spec = importlib.util.spec_from_file_location(
        "router_evaluation", Path(__file__).with_name("evaluate_router.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.local_provider(module.Settings.from_env())


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--split", choices=["development", "holdout", "contract"])
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    corpus = load_corpus(args.corpus)
    if not args.run:
        print(
            json.dumps(
                {
                    "prepared_only": True,
                    "model_calls": 0,
                    "target_calls": 0,
                    "corpus_version": corpus["version"],
                    "cases": len(corpus["cases"]),
                }
            )
        )
        return 0
    if not args.output or not 1 <= args.timeout <= 120:
        parser.error("--run requires a new private --output and a timeout within 1..120 seconds")
    # Exclusive local output intent also prevents uncertain evaluation reruns from
    # silently replacing results; no private raw model text or exception messages.
    with args.output.open("x", encoding="utf-8") as output:
        try:
            provider = configured_provider()
            result = asyncio.run(
                evaluate(
                    corpus,
                    provider,
                    split=args.split,
                    case_ids=set(args.ids or []),
                    timeout_seconds=args.timeout,
                )
            )
        except Exception:
            result = {
                "model_cases": 0,
                "passed": 0,
                "integration_target_calls": 0,
                "scope": "semantic_interpretation_only_not_end_to_end",
        "role_budget": {"max_tokens_ceiling": 768, "disable_thinking": True},
                "error": "local_provider_unavailable",
            }
        result["corpus_sha256"] = hashlib.sha256(args.corpus.read_bytes()).hexdigest()
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                "model_cases": result["model_cases"],
                "passed": result["passed"],
                "integration_target_calls": 0,
                "scope": result["scope"],
            }
        )
    )

    return int(bool(result.get("error")) or result["passed"] != result["model_cases"])


if __name__ == "__main__":
    raise SystemExit(main())
