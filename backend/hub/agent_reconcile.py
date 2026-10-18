"""Bounded read-only checks after acknowledged or uncertain API effects.

The predicate is persisted BEFORE dispatch. Lost responses never cause a second
mutation. Matching observations prove the requested state, not its causation.
"""

import time
from typing import Any

from hub.action_api import encode
from hub.agent_models import AgentJob, AgentStep
from hub.agent_tools import invoke, validate_tool
from hub.provider_settings import decrypt


def verify(
    factory: Any, cfg: Any, job_id: str, parent: int, document: dict[str, Any]
) -> dict[str, Any]:
    from hub.agent_runtime import gate, record

    rule = document["arguments"]["verification"]
    with factory() as db:
        job = db.get(AgentJob, job_id)
        assert job
        gate(db, cfg, job)
        step = record(
            db,
            job,
            "verification",
            {
                "message": "Vorgegebenen Sollzustand lesend prüfen",
                "effect_step": parent,
                "predicate": rule,
            },
        )
        step.status = "dispatching"
        sequence = step.sequence
        deadline = min(job.created + job.timeout_seconds, time.time() + rule["timeout_seconds"])
        db.commit()
    result: dict[str, Any] = {
        "effect_verified": False,
        "automatic_retry": False,
        "causation_verified": False,
        "attempts": 0,
        "verification_method": "prebound_read_predicate",
    }
    while time.time() < deadline and result["attempts"] < 180:
        result["attempts"] += 1
        try:
            with factory() as db:
                job = db.get(AgentJob, job_id)
                assert job
                profiles = gate(db, cfg, job)
                profile, rules, config = profiles[document["integration_id"]]
                args, effect = validate_tool(
                    profile.kind,
                    rules,
                    "http.verify",
                    {
                        "path": rule["path"],
                        "query": rule["query"],
                        "expected": rule["expected"],
                        "effect_step": parent,
                    },
                )
                assert not effect
                secret = (
                    decrypt(cfg, "integration:" + profile.id, profile.encrypted_secret)
                    if profile.encrypted_secret
                    else ""
                )
                db.commit()

                def boundary(job: AgentJob = job) -> None:
                    gate(db, cfg, job)
                    db.commit()

                observation = invoke(cfg, config, secret, "http.verify", args, rules, boundary)
                result["last_observation"] = observation
                result["effect_verified"] = observation.get("verification_passed") is True
        except PermissionError:
            result["authority_closed"] = True
            break
        except Exception:
            result["last_read_unavailable"] = True
        with factory() as db:
            step = db.get(AgentStep, (job_id, sequence))
            assert step
            step.result = encode(result)
            db.commit()
        if result["effect_verified"]:
            break
        time.sleep(min(rule["interval_seconds"], max(0, deadline - time.time())))
    with factory() as db:
        step = db.get(AgentStep, (job_id, sequence))
        assert step
        step.result, step.status = (
            encode(result),
            "succeeded" if result["effect_verified"] else "failed",
        )
        db.commit()
    return {**result, "verification_step": sequence}
