"""Procrastinate owns durable dispatch; no independent scheduler or retry queue."""

import asyncio
import json
import time

import procrastinate
import psycopg
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from hub.config import Settings
from hub.db import Message, Run, RunEvent, session_factory
from hub.execution import execute_run
from hub.policy import Privacy
from hub.providers import Providers
from hub.titles import execute_title


def conninfo(cfg: Settings) -> str:
    url = make_url(cfg.database_url)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("Durable worker requires postgresql+psycopg")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def enqueue(db: Session, cfg: Settings, run_id: str) -> None:
    # SQLAlchemy owns the transaction. Procrastinate inserts on its underlying
    # psycopg connection so no committed run can be stranded before dispatch.
    queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo(cfg)))
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, psycopg.Connection):
        raise ValueError("Unexpected database driver")
    raw.execute("SET LOCAL search_path TO hub_queue, public")
    queue.configure_task(name="hub.chat", queue="chat", connection=raw).defer(run_id=run_id)


def enqueue_title(db: Session, cfg: Settings, chat_id: str) -> None:
    queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo(cfg)))
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, psycopg.Connection):
        raise ValueError("Durable queue requires a PostgreSQL psycopg transaction")
    raw.execute("SET LOCAL search_path TO hub_queue, public")
    queue.configure_task(name="hub.title", queue="titles", connection=raw).defer(chat_id=chat_id)


def worker_app(cfg: Settings) -> procrastinate.App:
    queue = procrastinate.App(
        connector=procrastinate.PsycopgConnector(
            conninfo=conninfo(cfg),
            kwargs={"options": "-c search_path=hub_queue,public"},
            min_size=1,
            max_size=3,
        )
    )
    factory = session_factory(cfg.database_url)
    providers = Providers(cfg)

    @queue.task(name="hub.chat", queue="chat", retry=False)
    async def chat(run_id: str) -> None:
        # Only Procrastinate dispatches this task. A manually retried stalled job
        # must reconcile persisted output rather than repeat a provider call.
        with factory() as db:
            run = db.get(Run, run_id)
            if run and run.status in ("routing", "streaming"):
                events = db.scalars(
                    select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)
                ).all()
                output = "".join(json.loads(e.payload)["text"] for e in events if e.kind == "delta")
                if output:
                    # Strong restriction for crash-derived partial output.
                    db.add(
                        Message(
                            conversation_id=run.conversation_id,
                            role="assistant",
                            content=output,
                            label=Privacy.LOCAL_ONLY,
                        )
                    )
                run.status, run.finished = "interrupted", time.time()
                run.error = "Worker unterbrochen; gespeicherte Teilantwort wiederhergestellt"
                db.commit()
                return
        await execute_run(factory, cfg, providers, run_id)

    @queue.task(name="hub.title", queue="titles", retry=False)
    async def title(chat_id: str) -> None:
        await execute_title(factory, providers, chat_id)

    return queue


async def main() -> None:
    queue = worker_app(Settings.from_env())
    async with queue.open_async():
        # Single local inference slot. n8n remains the only schedule engine.
        await queue.run_worker_async(
            queues=["chat", "titles"], concurrency=1, shutdown_graceful_timeout=95
        )


if __name__ == "__main__":
    asyncio.run(main())
