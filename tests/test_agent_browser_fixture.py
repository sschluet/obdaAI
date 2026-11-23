"""UI provider separates semantic interpretation from administrative decisions."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from hub import agent_runtime
from hub.agent_intent import accept_semantic, infer, semantic_request
from hub.agent_tools import Rules
from hub.policy import ContextPart
from jsonschema import Draft202012Validator


def test_synthetic_browser_admin_provider_interprets_compound_goal_before_asking(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("The isolated agent fixture must handle both protocol turns")
        yield ""

    app = SimpleNamespace(
        state=SimpleNamespace(settings=SimpleNamespace(),
                              providers=SimpleNamespace(stream=forbidden)),
        middleware=lambda name: lambda fn: fn,
    )
    monkeypatch.setitem(sys.modules, "scripts.browser_fixture", SimpleNamespace(app=app))
    monkeypatch.setattr(agent_runtime, "invoke", agent_runtime.invoke)
    spec = importlib.util.spec_from_file_location(
        "synthetic_agent_fixture_test", Path(__file__).parents[1] / "scripts/agent_fixture.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    identifier = "11111111-1111-4111-8111-111111111111"
    profile = SimpleNamespace(id=identifier, kind="paperless", name="Paperless Aurora")
    selected = {identifier: (profile, Rules(enabled=True), {})}
    goal = "Ändere das synthetische Dokument. Frage zuerst nach dem gewünschten Titel."
    assert infer(goal, selected) is None  # The production shortcut stays conservative.
    contract = semantic_request(goal, selected)

    async def invoke(data):
        parts = [ContextPart(source_id="agent-policy", revision=1, content="Synthetic protocol"),
                 ContextPart(source_id="agent-context", revision=1, content=json.dumps(data))]
        return json.loads("".join([chunk async for chunk in module.stream(
            parts, ["system", "user"], external=False, grants=[],
        )]))

    output = asyncio.run(invoke({**contract["data"], "intent_schema": contract["schema"]}))
    Draft202012Validator(contract["schema"]).validate(output)
    intent = accept_semantic(output, selected)
    assert intent.mode == "admin" and intent.target_ids == [identifier]
    assert [requirement.kind for requirement in intent.requirements] == ["effect_postcondition"]
    answer = asyncio.run(invoke({
        "goal": goal, "history": [], "interfaces": [{"integration_id": identifier}],
    }))
    assert answer == {"kind": "ask",
                      "message": "Welchen Titel soll das synthetische Dokument erhalten?"}
    assert module.state == {"id": 1, "title": "Synthetisches Dokument"}
