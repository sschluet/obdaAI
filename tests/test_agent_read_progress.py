"""A successful read must not be dispatched repeatedly by a bounded read planner."""

import asyncio
from uuid import uuid4

from hub import agent_runtime as runtime
from test_agent_capability_runtime import agent, gateway, ha, set_pause, writes  # noqa: F401


def test_identical_successful_get_becomes_feedback_without_a_second_dispatch(
    ha, monkeypatch  # noqa: F811
):
    app, client, headers, cfg, identifier, chat, *_ = ha
    sent = []
    planned = []

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        sent.append(args["path"])
        return {"http_status": 200, "body": {"version": "synthetic"},
                "effect_verified": False}

    async def generate(factory, cfg, providers, job_id, instruction, data):
        planned.append(data)
        if len(planned) < 3:
            return {"kind": "tool", "message": "Version lesen", "integration_id": identifier,
                    "tool": "http", "arguments": {"method": "GET", "path": "/api/config"}}
        feedback = [s for s in data["history"] if s["kind"] == "feedback"]
        assert feedback[-1]["document"]["issues"][0]["type"] == "read_already_observed"
        return {"kind": "finish", "message": "Beobachtete Version: synthetic."}

    monkeypatch.setattr(runtime, "invoke", invoke)
    monkeypatch.setattr(runtime, "generate", generate)
    response = client.post(f"/api/conversations/{chat}/agent-runs", headers=headers, json={
        "request_id": str(uuid4()), "goal": "Prüfe ausschließlich lesend die HA-Version.",
        "read_only": True, "research_allowed": False,
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, job_id))
    job = client.get("/api/agent-runs/" + job_id).json()
    assert job["status"] == "observed", job
    assert sent == ["/api/", "/api/config"]
    assert len(planned) == 3
    assert not any(step["kind"] in {"effect", "ask"} for step in job["steps"])
