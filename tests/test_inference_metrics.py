import json

from hub.db import Base, Conversation, Run, session_factory
from hub.inference_metrics import inference_metrics


def test_latency_percentiles_use_only_finite_local_metadata_and_return_no_text(tmp_path):
    factory = session_factory("sqlite:///" + str(tmp_path / "metrics.sqlite"))
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as db:
        chat = Conversation(title="SYNTHETIC_PRIVATE_TITLE")
        db.add(chat)
        db.flush()
        for i in range(1, 21):
            db.add(
                Run(
                    conversation_id=chat.id,
                    provider="local",
                    status="succeeded",
                    routing_trace=json.dumps(
                        {
                            "inference_phases": {"queue_seconds": i, "prefill_seconds": i * 2},
                            "private": "SYNTHETIC_PRIVATE_PROMPT",
                        }
                    ),
                    first_content_seconds=i * 3,
                )
            )
        db.add(
            Run(
                conversation_id=chat.id,
                provider="openrouter",
                status="succeeded",
                first_content_seconds=999,
            )
        )
        db.add(
            Run(
                conversation_id=chat.id,
                provider="local",
                status="failed",
                routing_trace=json.dumps(
                    {
                        "inference_timeout_phase": "queue",
                        "inference_phases": {"queue_seconds": -1, "prefill_seconds": "private"},
                    }
                ),
            )
        )
        db.commit()
        result = inference_metrics(db)
    assert result["latency"]["queue"] == {"samples": 20, "p50_seconds": 10.0, "p95_seconds": 19.0}
    assert result["latency"]["prefill"]["p95_seconds"] == 38.0
    assert result["timeout_counts"] == {"queue": 1}
    assert "PRIVATE" not in json.dumps(result)
