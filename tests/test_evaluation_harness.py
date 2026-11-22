"""Evaluation contracts are synthetic and classification-only; mocks are not quality scores."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from hub.routing import Route

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Router:
    route_calls = 0

    def __init__(self, answer=None):
        self.answer = answer

    async def route(self, parts, roles):
        self.route_calls += 1
        assert all(part.label == "LOCAL_ONLY" for part in parts)
        return Route(
            capabilities=["chat"], model_class="local", reason="Synthetic", answer=self.answer
        )

    async def stream(self, *args, **kwargs):
        raise AssertionError("A router evaluation cannot call an answer provider")


def test_router_simple_case_requires_classification_without_inline_answer():
    module = script("evaluate_router")
    cases = [
        {"id": "synthetic", "prompt": "Was ist 2+2?", "capabilities": ["chat"], "simple": True}
    ]
    result = asyncio.run(module.evaluate(cases, provider=Router()))
    assert result["passed"] == 1 and result["answer_provider_calls"] == 0
    assert result["cases"][0]["classification_only"]
    rejected = asyncio.run(module.evaluate(cases, provider=Router(answer="4")))
    assert rejected["passed"] == 0
    cases[0]["answer_contains"] = "4"
    with pytest.raises(ValueError, match="obsolete"):
        asyncio.run(module.evaluate(cases, provider=Router()))


def test_router_corpus_contains_no_obsolete_answer_expectations():
    cases = json.loads((ROOT / "tests/fixtures/router-cases.json").read_text())
    assert all("answer_contains" not in case for case in cases)


class IntentProvider:
    local_json_schema = None

    def __init__(self, cases, *, error=None):
        self.expected = [row for row in cases if "contract" not in row["expect"]]
        self.calls = 0
        self.error = error

    async def stream(self, parts, roles, *, external, grants):
        assert external is False and grants == []
        assert roles == ["system", "user"]
        assert self.local_json_schema["properties"]["target_ids"]
        assert all(part.label == "LOCAL_ONLY" for part in parts)
        case = self.expected[self.calls]
        self.calls += 1
        assert json.loads(parts[1].content)["goal"] == case["prompt"]
        if self.error == "timeout":
            await asyncio.sleep(0.1)
        if self.error == "private-error":
            raise RuntimeError("SYNTHETIC-PRIVATE-TOKEN https://private.example.invalid")
        expected = case["expect"]
        payload = {
            "version": 1,
            "origin": "semantic",
            "mode": expected["modes"][0],
            "topic": "general",
            "research": False,
            "followup": False,
            "freshness": "current",
            "answer_kind": "general",
            "target_ids": expected["target_ids"],
            "requirements": expected["requirements"],
            "confidence": expected.get("confidence", ["certain"])[0],
        }
        if payload["mode"] == "admin":
            payload["requirements"] = [
                *payload["requirements"],
                *[
                    {"kind": "effect_postcondition", "integration_id": target}
                    for target in payload["target_ids"]
                    if not any(
                        r["kind"] == "effect_postcondition" and r["integration_id"] == target
                        for r in payload["requirements"]
                    )
                ],
            ]
        if self.error == "unknown-target":
            payload["target_ids"] = ["synthetic-unavailable"]
            payload["requirements"] = []
        raw = json.dumps(payload)
        yield raw[: len(raw) // 2]
        yield raw[len(raw) // 2 :]


def test_versioned_corpus_scorer_covers_splits_compound_goals_and_privacy_without_target_calls():
    module = script("evaluate_agent_prompts")
    corpus = module.load_corpus(module.DEFAULT_CORPUS)
    provider = IntentProvider(corpus["cases"])
    result = asyncio.run(module.evaluate(corpus, provider))
    assert result["passed"] == result["model_cases"] == provider.calls == 23
    assert result["integration_target_calls"] == result["cloud_calls"] == 0
    assert {"development", "holdout"} <= set(result["by_split"])
    contract = next(row for row in result["cases"] if row["contract_only"])
    assert contract["model_calls"] == 0 and contract["passed"]
    assert result["latency_seconds"]["median"] is not None
    assert all(
        row["first_token_seconds"] is not None
        for row in result["cases"]
        if not row["contract_only"]
    )


@pytest.mark.parametrize(
    "failure,category",
    [
        ("timeout", "model_timeout"),
        ("private-error", "model_unavailable"),
        ("unknown-target", "invalid_intent"),
    ],
)
def test_model_failures_are_measured_without_exception_or_prompt_payload_leak(failure, category):
    module = script("evaluate_agent_prompts")
    corpus = module.load_corpus(module.DEFAULT_CORPUS)
    corpus["cases"] = [corpus["cases"][0]]
    provider = IntentProvider(corpus["cases"], error=failure)
    result = asyncio.run(module.evaluate(corpus, provider, timeout_seconds=0.001))
    assert result["passed"] == 0 and result["cases"][0]["error"] == category
    assert "SYNTHETIC-PRIVATE-TOKEN" not in json.dumps(result)


def test_eval_main_is_inert_until_explicit_model_call_flag(monkeypatch, capsys):
    module = script("evaluate_agent_prompts")
    monkeypatch.setattr("sys.argv", ["evaluate_agent_prompts.py"])
    monkeypatch.setattr(
        module,
        "configured_provider",
        lambda: (_ for _ in ()).throw(
            AssertionError("Default invocation cannot read model credentials or call a provider")
        ),
    )
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["model_calls"] == 0


def test_semantic_role_budget_matches_production_interpretation_role():
    from dataclasses import dataclass

    @dataclass
    class Budget:
        local_max_tokens: int = 4096
        local_disable_thinking: bool = False

    module = script("evaluate_agent_prompts")
    corpus = module.load_corpus(ROOT / "tests/fixtures/agent-prompt-cases-v2.json")
    provider = IntentProvider(corpus["cases"])
    provider.settings = Budget()
    result = asyncio.run(module.evaluate(corpus, provider))
    assert provider.settings.local_max_tokens == 768
    assert provider.settings.local_disable_thinking is True
    assert result["role_budget"] == {"max_tokens_ceiling": 768, "disable_thinking": True}

    provider = IntentProvider(corpus["cases"])
    provider.settings = Budget(local_max_tokens=256)
    asyncio.run(module.evaluate(corpus, provider))
    assert provider.settings.local_max_tokens == 256
