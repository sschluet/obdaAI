"""Exercise actual memory queue handlers without opening a queue or provider connection."""

import asyncio
from types import SimpleNamespace

import pytest
from hub import jobs
from hub.config import Settings
from hub.db import Base
from hub.memory_models import MemoryLearningJob
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def worker(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(jobs, "session_factory", lambda url: factory)
    cfg = Settings(database_url="postgresql+psycopg://hub@127.0.0.1/hub_ci")
    queue = jobs.worker_app(cfg, include_maintenance=False)
    yield queue, factory, cfg
    engine.dispose()


def learning(factory, status):
    with factory() as db:
        job = MemoryLearningJob(
            source_message_id="source",
            source_message_revision=1,
            source_conversation_id="chat",
            source_sha256="a" * 64,
            settings_revision=0,
            status=status,
        )
        db.add(job)
        db.commit()
        return job.id


def test_duplicate_running_memory_delivery_never_revokes_live_job(worker, monkeypatch):
    queue, factory, _ = worker
    identifier = learning(factory, "running")

    async def forbidden(*args, **kwargs):
        pytest.fail("A running job must not replay uncertain inference")

    monkeypatch.setattr("hub.memory_learning.execute_learning", forbidden)
    asyncio.run(queue.tasks["hub.memory"].func(job_id=identifier))
    with factory() as db:
        row = db.get(MemoryLearningJob, identifier)
        assert row.status == "running" and row.error == "" and row.finished is None


def test_queued_memory_handler_delegates_exact_job(worker, monkeypatch):
    queue, factory, cfg = worker
    identifier = learning(factory, "queued")
    observed = []

    async def execute(actual_factory, config, job_id):
        observed.append((actual_factory, config, job_id))

    monkeypatch.setattr("hub.memory_learning.execute_learning", execute)
    asyncio.run(queue.tasks["hub.memory"].func(job_id=identifier))
    assert observed == [(factory, cfg, identifier)]


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_completed_memory_delivery_is_model_free_idempotent(worker, monkeypatch, status):
    queue, factory, _ = worker
    identifier = learning(factory, status)

    def forbidden(*args, **kwargs):
        pytest.fail("Completed delivery must not construct an inference adapter")

    monkeypatch.setattr("hub.provider_api.adapter", forbidden)
    asyncio.run(queue.tasks["hub.memory"].func(job_id=identifier))
    with factory() as db:
        assert db.get(MemoryLearningJob, identifier).status == status


def test_bounded_periodic_memory_index_is_independent_of_extraction(worker, monkeypatch):
    queue, factory, cfg = worker
    observed = []

    async def index(actual_factory, config, *, limit):
        observed.append((actual_factory, config, limit))

    monkeypatch.setattr("hub.memory_embeddings.refresh_embeddings", index)
    asyncio.run(queue.tasks["hub.memory-index"].func(timestamp=0))
    assert observed == [(factory, cfg, 20)]


@pytest.mark.parametrize("status", ["queued", "running"])
def test_requeue_only_proven_stall_reconciles_running_inference(worker, status):
    queue, factory, _ = worker
    identifier = learning(factory, status)
    stalled = SimpleNamespace(task_kwargs={"job_id": identifier})
    observed, retried = [], []

    class Manager:
        async def get_stalled_jobs(self, *, task_name, seconds_since_heartbeat):
            observed.append((task_name, seconds_since_heartbeat))
            return [stalled] if task_name == "hub.memory" else []

        async def retry_job(self, job):
            retried.append(job)

    queue.job_manager = Manager()
    asyncio.run(jobs.requeue_stalled(queue, factory))
    assert ("hub.memory", 60) in observed and ("hub.memory-index", 60) in observed
    assert retried == [stalled]
    with factory() as db:
        row = db.get(MemoryLearningJob, identifier)
        if status == "running":
            assert row.status == "failed" and row.error == "worker_interrupted" and row.finished
        else:
            assert row.status == "queued" and row.error == "" and row.finished is None
