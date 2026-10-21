"""A blocking vault scan must not block queue heartbeats or uploaded files."""

import asyncio
import threading
from contextlib import asynccontextmanager

import pytest
from hub import jobs
from hub.config import Settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "flag,expected",
    [
        ("--sources", ["sources"]),
        ("--vault", ["vault-maintenance"]),
        ("--artifacts", ["artifacts"]),
    ],
)
async def test_worker_queue_selection(monkeypatch, flag, expected):
    class Queue:
        @asynccontextmanager
        async def open_async(self):
            yield

        async def run_worker_async(self, **kwargs):
            assert kwargs["queues"] == expected

    async def reconcile(queue, factory=None):
        pass

    monkeypatch.setattr(jobs.sys, "argv", ["hub.jobs", flag])
    monkeypatch.setattr(jobs, "worker_app", lambda *a, **kw: Queue())
    monkeypatch.setattr(jobs, "requeue_stalled", reconcile)
    await jobs.main()


@pytest.mark.anyio
async def test_vault_scan_retains_event_loop_and_own_transaction(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    transaction = []

    class DB:
        def __enter__(self):
            transaction.append(threading.get_ident())
            return self

        def __exit__(self, *a):
            pass

        def commit(self):
            transaction.append("committed")

    monkeypatch.setattr(jobs, "session_factory", lambda url: DB)

    def scan(*a, **kw):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr("hub.memory.reconcile", scan)
    cfg = Settings(database_url="postgresql+psycopg://hub@127.0.0.1/hub_ci", vault_dir="/synthetic")
    queue = jobs.worker_app(cfg, include_maintenance=False)
    worker = asyncio.create_task(queue.tasks["hub.vault-reconcile"].func(timestamp=1))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set() and not worker.done()
        assert transaction[0] != threading.get_ident()
    finally:
        release.set()
        await worker
    assert transaction[-1] == "committed"
