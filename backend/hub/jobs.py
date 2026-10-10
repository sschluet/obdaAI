"""Procrastinate owns durable dispatch; no independent scheduler or retry queue."""

import asyncio
import json
import sys
import time
from typing import Any

import procrastinate
import psycopg
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from hub.config import Settings
from hub.db import Message, Run, RunEvent, session_factory
from hub.execution import execute_run
from hub.policy import Privacy
from hub.provider_api import execute_probe
from hub.provider_settings import runtime_provider
from hub.providers import Providers
from hub.providers import Providers as AdapterClass
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
    queue.configure_task(name="hub.chat", queue="chat", priority=10, connection=raw).defer(
        run_id=run_id
    )


def enqueue_title(db: Session, cfg: Settings, chat_id: str) -> None:
    queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo(cfg)))
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, psycopg.Connection):
        raise ValueError("Durable queue requires a PostgreSQL psycopg transaction")
    raw.execute("SET LOCAL search_path TO hub_queue, public")
    queue.configure_task(name="hub.title", queue="titles", priority=-10, connection=raw).defer(
        chat_id=chat_id
    )


def enqueue_probe(db: Session, cfg: Settings, test_id: str) -> None:
    queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo(cfg)))
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, psycopg.Connection):
        raise ValueError("Durable queue requires psycopg")
    raw.execute("SET LOCAL search_path TO hub_queue, public")
    queue.configure_task(name="hub.probe", queue="tests", priority=5, connection=raw).defer(
        test_id=test_id
    )


def enqueue_source(db: Session, cfg: Settings, source_id: str) -> None:
    queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo(cfg)))
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, psycopg.Connection):
        raise ValueError("Durable queue requires psycopg")
    raw.execute("SET LOCAL search_path TO hub_queue, public")
    queue.configure_task(name="hub.extract", queue="sources", priority=-20, connection=raw).defer(
        source_id=source_id
    )


def enqueue_knowledge(db: Session, cfg: Settings, connection_id: str, revision: int) -> None:
    queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo(cfg)))
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, psycopg.Connection):
        raise ValueError("Durable queue requires psycopg")
    raw.execute("SET LOCAL search_path TO hub_queue, public")
    queue.configure_task(
        name="hub.knowledge-index", queue="sources", priority=-15, connection=raw
    ).defer(connection_id=connection_id, revision=revision)


def enqueue_task_read(db: Session, cfg: Settings, run_id: str) -> None:
    queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo(cfg)))
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, psycopg.Connection):
        raise ValueError("Durable task requires psycopg")
    raw.execute("SET LOCAL search_path TO hub_queue, public")
    queue.configure_task(name="hub.task-read", queue="tasks", priority=0, connection=raw).defer(
        run_id=run_id
    )


def enqueue_artifact(db: Session, cfg: Settings, artifact_id: str, revision: int) -> None:
    queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo(cfg)))
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, psycopg.Connection):
        raise ValueError("Durable artifact requires psycopg")
    raw.execute("SET LOCAL search_path TO hub_queue, public")
    queue.configure_task(name="hub.artifact", queue="artifacts", priority=-5, connection=raw).defer(
        artifact_id=artifact_id, revision=revision
    )


def worker_app(cfg: Settings, *, include_maintenance: bool = True) -> procrastinate.App:
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

    def maintenance_schedule(task: Any) -> Any:
        return queue.periodic(cron="* * * * *")(task) if include_maintenance else task

    @queue.task(name="hub.artifact", queue="artifacts", retry=False)
    async def artifact(artifact_id: str, revision: int) -> None:
        from hub.artifacts import execute_artifact

        await execute_artifact(factory, cfg, artifact_id, revision)

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
                            run_id=run.id,
                            role="assistant",
                            content=output,
                            label=Privacy.LOCAL_ONLY,
                        )
                    )
                run.status, run.finished = "interrupted", time.time()
                run.error = (
                    "Worker unterbrochen; gespeicherte Teilantwort wiederhergestellt"
                    if output
                    else "Worker unterbrochen; kein neuer Modellaufruf"
                )
                db.commit()
                return
        await execute_run(factory, cfg, providers, run_id)

    @queue.task(name="hub.title", queue="titles", retry=False)
    async def title(chat_id: str) -> None:
        title_providers = providers
        if isinstance(providers, AdapterClass):
            _, title_providers, _ = runtime_provider(factory, cfg)
        await execute_title(factory, title_providers, chat_id)

    @queue.task(name="hub.extract", queue="sources", retry=False)
    async def extract(source_id: str) -> None:
        from hub.knowledge import extract_source

        await extract_source(factory, cfg, source_id)

    @queue.task(name="hub.knowledge-index", queue="sources", retry=False)
    async def knowledge_index(connection_id: str, revision: int) -> None:
        from hub.knowledge_connections import index_connection

        await index_connection(factory, cfg, connection_id, revision)

    @queue.task(name="hub.probe", queue="tests", retry=False)
    async def probe(test_id: str) -> None:
        await execute_probe(factory, cfg, test_id)

    @queue.task(name="hub.task-read", queue="tasks", retry=False)
    async def task_read(run_id: str) -> None:
        from hub.task_model import execute_task

        await execute_task(factory, cfg, run_id)

    @maintenance_schedule
    @queue.task(
        name="hub.vault-reconcile",
        queue="vault-maintenance",
        retry=False,
        queueing_lock="hub.vault-reconcile",
    )
    async def vault_reconcile(timestamp: int) -> None:
        if cfg.vault_dir:
            from pathlib import Path

            from hub.memory import reconcile as reconcile_vault

            def scan() -> None:
                with factory() as db:
                    reconcile_vault(
                        db,
                        Path(cfg.vault_dir),
                        allow_memory_writes=cfg.vault_writable,
                        expected_fs=cfg.vault_fs_type,
                    )
                    db.commit()

            # SSHFS/SQL indexing must not block Procrastinate heartbeat or shutdown.
            await asyncio.to_thread(scan)

    @maintenance_schedule
    @queue.task(
        name="hub.reconcile",
        queue="maintenance",
        priority=20,
        queueing_lock="hub.reconcile",
        retry=False,
    )
    async def reconcile(timestamp: int) -> None:
        await requeue_stalled(queue)

    return queue


async def requeue_stalled(queue: procrastinate.App) -> None:
    # Only upstream heartbeats prove a worker stalled; never infer from job age.
    for task in (
        "hub.chat",
        "hub.title",
        "hub.probe",
        "hub.extract",
        "hub.knowledge-index",
        "hub.task-read",
        "hub.artifact",
    ):
        for job in await queue.job_manager.get_stalled_jobs(
            task_name=task, seconds_since_heartbeat=60
        ):
            await queue.job_manager.retry_job(job)


async def cleanup_loop(cfg: Settings, role: str) -> None:
    from hub.deletion_cleanup import process_pending

    factory = session_factory(cfg.database_url)
    while True:
        try:
            await asyncio.to_thread(process_pending, factory, cfg, role)
        except Exception:
            pass  # Durable pending rows retry after transient DB/storage interruptions.
        await asyncio.sleep(2)


async def main() -> None:
    cfg = Settings.from_env()
    cleanup = (
        asyncio.create_task(cleanup_loop(cfg, "source" if "--sources" in sys.argv else "artifact"))
        if any(flag in sys.argv for flag in ("--sources", "--artifacts"))
        else None
    )
    queue = worker_app(
        cfg,
        include_maintenance=not any(flag in sys.argv for flag in ("--artifacts", "--sources")),
    )
    async with queue.open_async():
        await requeue_stalled(queue)
        # Single local inference slot. n8n remains the only schedule engine.
        await queue.run_worker_async(
            queues=["artifacts"]
            if "--artifacts" in sys.argv
            else ["sources"]
            if "--sources" in sys.argv
            else ["vault-maintenance"]
            if "--vault" in sys.argv
            else ["chat", "tests", "tasks", "titles", "maintenance"],
            concurrency=1,
            shutdown_graceful_timeout=95,
        )

    if cleanup:
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
