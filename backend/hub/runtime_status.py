"""Authenticated, read-only diagnostics. Observation is never an inference readiness test."""

import json
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from hub.auth import require_session
from hub.config import Settings
from hub.db import LoginSession, ProviderConfig, ProviderTest
from hub.inference_capacity import capacity_observation
from hub.inference_metrics import inference_metrics
from hub.schedule_api import scheduler_status

Auth = Annotated[LoginSession, Depends(require_session)]


def worker_observation(
    factory: sessionmaker[Session], *, sqlite: bool, now: float,
) -> dict[str, Any]:
    if sqlite:
        return {"mode": "in_process", "status": "not_applicable", "heartbeat_age_seconds": None,
                "scope": "development_process"}
    try:
        with factory() as db:
            latest = db.execute(text(
                "SELECT EXTRACT(EPOCH FROM MAX(last_heartbeat)) "
                "FROM hub_queue.procrastinate_workers"
            )).scalar_one_or_none()
        delta = now - float(latest) if latest is not None else None
        age = max(0, int(delta)) if delta is not None else None
        return {"mode": "postgres_worker", "status": "unknown" if age is None else (
            "observed" if delta is not None and 0 <= delta <= 60 else "stale"
        ), "heartbeat_age_seconds": age, "scope": "worker_processes_not_individual_queues"}
    except (SQLAlchemyError, TypeError, ValueError):
        return {"mode": "postgres_worker", "status": "unavailable", "heartbeat_age_seconds": None,
                "scope": "worker_processes_not_individual_queues"}


def runtime_status(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> dict[str, Any]:
    now = time.time()
    result: dict[str, Any] = {
        "liveness": {"status": "ok"},
        "database": {"status": "unknown"},
        "worker": {"status": "unknown"},
        "scheduler": {"status": "unknown"},
        "local": {"configured": False, "providers": [], "planner_readiness": "unknown",
                  "readiness": "not_probed_by_this_request"},
        "intent_interpretation": {
            "degraded": getattr(app.state, "intent_interpretation_degraded", None),
            "scope": "this_api_process", "readiness": "unknown",
        },
        "timeouts": {"first_token_seconds": cfg.local_first_token_timeout,
                     "idle_seconds": cfg.local_timeout, "queue_seconds": cfg.local_queue_timeout},
    }
    try:
        with factory() as db:
            db.execute(select(1))
            result["database"] = {"status": "ok"}
            result["inference"] = inference_metrics(db)
            rows = list(db.scalars(select(ProviderConfig).where(ProviderConfig.kind == "local")))
            for row in rows:
                try:
                    config = json.loads(row.config)
                    configured = bool(
                        row.enabled and config.get("model") and config.get("base_url")
                    )
                    idle = int(config.get("timeout", cfg.local_timeout))
                except (ValueError, TypeError, AttributeError):
                    configured, idle = False, cfg.local_timeout
                probes: dict[str, Any] = {}
                for mode in ("model", "planner"):
                    probe = db.scalar(select(ProviderTest).where(
                        ProviderTest.provider_id == row.id, ProviderTest.mode == mode,
                    ).order_by(ProviderTest.created.desc(), ProviderTest.id).limit(1))
                    probes[mode] = None if probe is None else {
                        "status": probe.status, "mode": mode, "revision": probe.revision,
                        "current_revision": probe.revision == row.revision,
                        "age_seconds": max(0, int(now - probe.created)),
                        "evidence": "last_known_probe_not_current_readiness",
                    }
                planner = probes["planner"]
                result["local"]["providers"].append({
                    "id": row.id, "revision": row.revision, "enabled": row.enabled,
                    "is_default": row.is_default, "configured": configured,
                    "capacity": capacity_observation(
                        cfg.source_dir, str(config.get("base_url", ""))
                    )
                    if configured else "not_observed",
                    "capacity_scope": "this_app_volume_not_all_model_clients",
                    "idle_seconds": idle, "last_model_probe": probes["model"],
                    "last_planner_probe": planner,
                    "planner_readiness": "last_probe_succeeded" if (
                        configured and planner and planner["current_revision"]
                        and planner["status"] == "succeeded"
                    ) else "unknown",
                })
            result["local"]["configured"] = any(
                item["configured"] for item in result["local"]["providers"]
            )
            pulse = scheduler_status(db, cfg, now)
            result["scheduler"] = {"status": "observed" if pulse["healthy"] else (
                "stale" if pulse["configured"] else "not_configured"
            ), "configured": pulse["configured"], "healthy": pulse["healthy"],
                "heartbeat_age_seconds": None if pulse["last_tick"] is None else
                max(0, int(now - pulse["last_tick"])), "scope": "scheduler_not_model_or_worker"}
    except (SQLAlchemyError, OSError, ValueError, TypeError):
        result["database"] = {"status": "unavailable"}
        result["local"] = {"configured": None, "providers": [], "planner_readiness": "unknown",
                           "readiness": "unavailable"}
    result["worker"] = worker_observation(
        factory, sqlite=cfg.database_url.startswith("sqlite"), now=now,
    )
    return result


def install_runtime_status(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/runtime-status")
    def get_status(auth: Auth) -> dict[str, Any]:
        return runtime_status(app, cfg, factory)
