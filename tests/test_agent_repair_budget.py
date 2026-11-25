"""Repairs are bounded per no-progress episode and globally, without target dispatch."""
import pytest
from hub import agent_runtime as runtime
from hub.action_api import encode
from hub.agent_models import AgentJob
from test_agent_capability_runtime import start

pytest_plugins = ["test_agent_capability_runtime"]


def test_format_repairs_reset_only_after_new_evidence_and_keep_global_cap(ha):
    app, _, _, cfg, target, *_ = ha
    identifier = start(ha, research_allowed=False)
    with app.state.sessions() as db:
        job = db.get(AgentJob, identifier)
        for episode in range(4):
            for _ in range(2):
                runtime.format_feedback(db, cfg, job, {"kind": "tool"}, [{"type": "synthetic"}])
            with pytest.raises(runtime.AgentFormatExhausted):
                runtime.format_feedback(db, cfg, job, {"kind": "tool"}, [{"type": "synthetic"}])
            read = runtime.record(db, job, "read", {
                "integration_id": target, "tool": "http",
                "arguments": {"method": "GET", "path": "/api/synthetic/" + str(episode)},
            })
            read.status = "succeeded"
            read.result = encode({"http_status": 200, "body": {"observed": episode}})
            db.flush()
        with pytest.raises(runtime.AgentFormatExhausted):
            runtime.format_feedback(db, cfg, job, {"kind": "tool"}, [{"type": "synthetic"}])
        assert len([s for s in runtime.steps(db, identifier) if s.kind == "feedback"]) == 8
