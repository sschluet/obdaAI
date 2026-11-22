"""Bounded metadata-only latency aggregates. Never return stored prompts or outputs."""

import json
import math
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hub.db import Run


def _percentiles(values: list[float]) -> dict[str, float | int | None]:
    values.sort()
    return {
        "samples": len(values),
        **{
            name: round(values[max(0, math.ceil(len(values) * fraction) - 1)], 3)
            if values
            else None
            for name, fraction in (("p50_seconds", 0.5), ("p95_seconds", 0.95))
        },
    }


def inference_metrics(db: Session) -> dict[str, Any]:
    rows = db.execute(
        select(Run.routing_trace, Run.first_content_seconds)
        .where(
            Run.started >= time.time() - 30 * 86400,
            Run.provider == "local",
        )
        .order_by(Run.started.desc())
        .limit(1000)
    ).all()
    times: dict[str, list[float]] = {"queue": [], "prefill": [], "first_content": []}
    failures: dict[str, int] = {}
    for raw, first in rows:
        try:
            trace = json.loads(raw or "{}")
        except (ValueError, TypeError):
            continue
        phases = trace.get("inference_phases", {}) if isinstance(trace, dict) else {}
        if not isinstance(phases, dict):
            phases = {}
        for name, value in (
            ("queue", phases.get("queue_seconds")),
            ("prefill", phases.get("prefill_seconds")),
            ("first_content", first),
        ):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if math.isfinite(value) and value >= 0:
                    times[name].append(float(value))
        phase = trace.get("inference_timeout_phase") if isinstance(trace, dict) else None
        if phase in {"queue", "first_content", "idle"}:
            failures[phase] = failures.get(phase, 0) + 1
    return {
        "scope": "latest_1000_local_runs_in_30_days",
        "runs_sampled": len(rows),
        "latency": {key: _percentiles(values) for key, values in times.items()},
        "timeout_counts": failures,
        "readiness": "historical_not_current_readiness",
    }
