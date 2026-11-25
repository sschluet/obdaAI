"""Intrinsic HA update attributes stay in update.*, with one private schema repair."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from hub.agent_intent import (
    EntityOutcome,
    RequestIntent,
    Requirement,
    accept_semantic,
    semantic_request,
)
from hub.db import ProviderConfig, Run
from hub.request_interpretation import interpret
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy import select

pytest_plugins = ["test_provider_settings"]
PROFILES = {"ha": SimpleNamespace(kind="home_assistant", name="Synthetic HA")}
GOAL = "Bitte prüfe Home Assistant und spiele alle ausstehenden Update ein"


def payload(domain="update"):
    return RequestIntent(
        mode="admin",
        topic="inventory",
        target_ids=["ha"],
        requirements=[
            Requirement(kind="entity_states", domain="update", integration_id="ha"),
            Requirement(
                kind="effect_postcondition",
                integration_id="ha",
                outcome=EntityOutcome(
                    domain="update",
                    state="off",
                    scope="all_observed",
                    selection_state="on",
                    attribute_from_initial={"installed_version": "latest_version"},
                ),
            ),
        ],
    ).model_dump(mode="json") | {
        "requirements": [
            {"kind": "entity_states", "domain": "update", "integration_id": "ha", "outcome": None},
            {
                "kind": "effect_postcondition",
                "domain": "",
                "integration_id": "ha",
                "outcome": {
                    "domain": domain,
                    "state": "off",
                    "scope": "all_observed",
                    "selection_state": "on",
                    "attribute_from_initial": {"installed_version": "latest_version"},
                },
            },
        ]
    }


@pytest.mark.parametrize(
    "mapping",
    [
        {"installed_version": "latest_version"},
        {"custom": "installed_version"},
        {"latest_version": "custom"},
        {"custom": "latest_version"},
    ],
)
def test_schema_and_validator_reject_version_attributes_in_invented_domain(mapping):
    value = payload("supervisor")
    value.pop("origin")
    value.pop("version")
    value["requirements"][1]["outcome"]["attribute_from_initial"] = mapping
    advertised = {**value, "requirements": list(reversed(value["requirements"]))}
    assert not Draft202012Validator(semantic_request(GOAL, PROFILES)["schema"]).is_valid(advertised)
    with pytest.raises(ValidationError) as caught:
        accept_semantic(value, PROFILES, goal=GOAL)
    assert "outcome_version_domain" in {e["type"] for e in caught.value.errors()}


@pytest.mark.parametrize(
    "domain,mapping",
    [
        ("update", {"installed_version": "latest_version"}),
        ("custom_domain", {"current_scalar": "desired_scalar"}),
        ("light", {}),
    ],
)
def test_schema_retains_update_and_custom_scalar_goal_contracts(domain, mapping):
    value = payload(domain)
    value.pop("origin")
    value.pop("version")
    value["requirements"][1]["outcome"]["attribute_from_initial"] = mapping
    advertised = {**value, "requirements": list(reversed(value["requirements"]))}
    assert Draft202012Validator(semantic_request(GOAL, PROFILES)["schema"]).is_valid(advertised)
    assert accept_semantic(value, PROFILES).requirements[1].outcome.domain == domain


@pytest.mark.parametrize("repair", ["valid", "invalid", "revoked", "http_error"])
def test_real_local_interpreter_repairs_once_and_preserves_final_boundary(
    managed,
    monkeypatch,
    repair,
):
    app, _, _, cfg = managed
    original = httpx.AsyncClient
    bodies = []
    invalid = payload("supervisor")
    invalid["requirements"][1]["outcome"]["selection_state"] = "SYNTHETIC_SECRET_INVALID_MODEL_TEXT"

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if repair == "http_error":
            return httpx.Response(401, text="SYNTHETIC_SECRET_HTTP_ERROR")
        if len(bodies) == 1:
            answer = invalid
            if repair == "revoked":
                with app.state.sessions() as db:
                    db.get(ProviderConfig, "local-default").enabled = False
                    db.commit()
        else:
            assert "outcome_version_domain" in body["messages"][1]["content"]
            assert "SYNTHETIC_SECRET_INVALID_MODEL_TEXT" not in json.dumps(body)
            answer = invalid if repair == "invalid" else payload()
        return httpx.Response(
            200,
            text="data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {"content": json.dumps(answer)},
                        }
                    ]
                }
            )
            + "\n\ndata: [DONE]\n\n",
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(handler),
            **kw,
        ),
    )
    if repair == "valid":
        result = asyncio.run(interpret(app.state.sessions, cfg, GOAL, PROFILES))
        assert result.mode == "admin" and len(result.requirements) == 2
        assert result.requirements[1].outcome.domain == "update"
        assert len(bodies) == 2
    else:
        with pytest.raises((ValidationError, PermissionError, httpx.HTTPStatusError)):
            asyncio.run(interpret(app.state.sessions, cfg, GOAL, PROFILES))
        assert len(bodies) == (2 if repair == "invalid" else 1)
    with app.state.sessions() as db:
        runs = db.scalars(select(Run)).all()
        assert len(runs) == 1
        run = runs[0]
        assert run.status == ("succeeded" if repair == "valid" else "failed")
        trace = json.loads(run.routing_trace)
        assert "SYNTHETIC_SECRET" not in run.routing_trace + run.error + run.context_snapshot
        if repair != "http_error":
            assert trace["semantic_attempts"][0] == {
                "status": "invalid",
                "issue": "outcome_version_domain",
            }
        if repair == "valid":
            assert trace["semantic_attempts"][-1] == {"status": "succeeded"}


def test_semantic_repair_has_one_total_deadline_not_two_per_attempt(managed, monkeypatch):
    app, _, _, cfg = managed
    original = httpx.AsyncClient
    calls = []
    deadlines = []

    def bounded_timeout(seconds):
        deadlines.append(seconds)
        return asyncio.timeout(1)

    monkeypatch.setattr(
        "hub.request_interpretation.asyncio",
        SimpleNamespace(
            timeout=bounded_timeout,
            CancelledError=asyncio.CancelledError,
        ),
    )

    async def handler(request):
        calls.append(True)
        await asyncio.sleep(0.65)
        return httpx.Response(
            200,
            text="data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {"content": json.dumps(payload("supervisor"))},
                        }
                    ]
                }
            )
            + "\n\ndata: [DONE]\n\n",
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(handler),
            **kw,
        ),
    )
    with pytest.raises(TimeoutError):
        asyncio.run(
            interpret(
                app.state.sessions,
                cfg,
                GOAL,
                PROFILES,
            )
        )
    assert len(calls) == 2
    assert deadlines == [min(cfg.generation_timeout, 120)]
    with app.state.sessions() as db:
        run = db.scalar(select(Run))
        assert run.status == "failed"
        assert json.loads(run.routing_trace)["semantic_attempts"] == [
            {
                "status": "invalid",
                "issue": "outcome_version_domain",
            }
        ]


def test_compatible_regular_identifier_language_excludes_only_reserved_literals():
    import random
    import re
    import string

    from hub.agent_intent import _non_version_attribute_pattern

    pattern = re.compile(_non_version_attribute_pattern())
    reserved = {"installed_version", "latest_version"}
    examples = {"", "a" * 64, "a" * 65, "0bad", "bad-hyphen", "Upper"}
    for word in reserved:
        examples.update(word[:n] for n in range(1, len(word) + 1))
        examples.update([word + "x", word + "0", word + "_", "x" + word])
        examples.update(word[:n] + "x" + word[n + 1 :] for n in range(len(word)))
    rng = random.Random(217)
    examples.update(
        "".join(rng.choices(string.ascii_lowercase + string.digits + "_", k=n))
        for n in range(1, 66)
        for _ in range(5)
    )
    for value in examples:
        expected = bool(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)) and value not in reserved
        assert bool(pattern.fullmatch(value)) == expected, value


def test_semantic_wire_uses_supported_union_not_conditional_or_negated_schema():
    schema = semantic_request(GOAL, PROFILES)["schema"]
    branches = schema["$defs"]["EntityOutcome"]["anyOf"]
    assert branches[0]["properties"]["domain"]["const"] == "update"

    def visit(value):
        if isinstance(value, dict):
            assert not {"if", "then", "else", "not", "propertyNames"} & set(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)


def test_admin_wire_requires_actual_postcondition_first_without_changing_canonical_order():
    original = payload()
    original.pop("origin")
    original.pop("version")
    validator = Draft202012Validator(semantic_request(GOAL, PROFILES)["schema"])
    assert not validator.is_valid(original)
    valid = {**original, "requirements": list(reversed(original["requirements"]))}
    assert validator.is_valid(valid)
    for requirements in ([], [original["requirements"][0]], [original["requirements"][0]] * 2):
        assert not validator.is_valid({**original, "requirements": requirements})
    # Saved contracts remain order-agnostic; wire ordering never commands execution.
    accepted = accept_semantic(original, PROFILES)
    assert accepted.requirements[0].kind == "entity_states"
    assert accepted.requirements[1].kind == "effect_postcondition"
