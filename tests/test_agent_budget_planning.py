"""Exhausting the write budget must preserve an outstanding read verification."""

import asyncio

from hub import agent_runtime as runtime
from hub.agent_models import AgentJob
from test_agents import effect, start

pytest_plugins = ["test_agents"]


def test_last_unverified_effect_still_advertises_independent_verification(agent, monkeypatch):
    app, client, _, cfg, identifier, *_ = agent
    job_id = start(agent)
    with app.state.sessions() as db:
        db.get(AgentJob, job_id).max_effects = 1
        db.commit()
    turns, writes = [], []

    async def model(*args):
        data = args[-1]
        turns.append(data)
        if len(turns) == 1:
            return effect(agent)
        if len(turns) == 2:
            assert data["remaining_effects"] == 0
            assert "http.verify" in data["tools"] and not data["read_only"]
            return {"kind": "tool", "message": "Check actual title", "tool": "http.verify",
                    "integration_id": identifier, "arguments": {
                        "path": "/api/documents/1/", "effect_step": 1,
                        "expected": {"/body/title": "After"}}}
        assert data["remaining_effects"] == 0 and data["read_only"]
        assert "http.verify" not in data["tools"]
        return {"kind": "finish", "message": "Verified title"}

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        if args["method"] == "PATCH":
            writes.append(args)
            agent[6]["title"] = args["body"]["title"]
        return {"body": dict(agent[6]), "effect_verified": False,
                "verification_passed": agent[6]["title"] == "After"}

    monkeypatch.setattr(runtime, "generate", model)
    monkeypatch.setattr(runtime, "invoke", invoke)
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    result = client.get("/api/agent-runs/" + job_id).json()
    assert result["status"] == "succeeded", result
    assert len(turns) == 3 and len(writes) == 1
    assert result["steps"][0]["result"]["effect_verified"] is True
