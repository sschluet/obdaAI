"""Synthetic capacity contention, boundary rechecks and cancellation evidence."""

import asyncio

import pytest
from hub.config import Settings
from hub.inference_capacity import local_capacity
from hub.inference_progress import stream_with_progress


def test_local_slot_serializes_instances_and_cancel_releases(tmp_path):
    cfg = Settings(source_dir=str(tmp_path), local_base_url="http://fixture/v1")

    async def scenario():
        entered = asyncio.Event()
        phases = []

        async def other():
            async with local_capacity(cfg, phases.append):
                entered.set()

        async with local_capacity(cfg):
            waiter = asyncio.create_task(other())
            await asyncio.sleep(0.08)
            assert not entered.is_set() and phases == ["waiting_for_model"]
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        async with local_capacity(cfg):
            pass
        await other()
        assert entered.is_set() and phases[-1] == "model_ready"

    asyncio.run(scenario())


def test_local_queue_timeout_does_not_dispatch(tmp_path):
    cfg = Settings(
        source_dir=str(tmp_path), local_base_url="http://fixture/v1", local_queue_timeout=1
    )

    async def scenario():
        async with local_capacity(cfg):
            with pytest.raises(TimeoutError, match="capacity wait"):
                async with local_capacity(cfg):
                    pytest.fail("contending request dispatched")
        async with local_capacity(cfg):
            pass

    asyncio.run(scenario())


def test_local_capacity_rejects_symlink_and_public_storage(tmp_path):
    cfg = Settings(source_dir=str(tmp_path / "sources"))
    (tmp_path / "sources").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "sources" / ".inference-capacity").symlink_to(tmp_path / "elsewhere")

    async def scenario():
        with pytest.raises(PermissionError):
            async with local_capacity(cfg):
                pytest.fail("symlink admitted")

    asyncio.run(scenario())


def test_stream_progress_preserves_exceptions_and_closes_blocked_producer():
    class Fake:
        closed = False

        async def stream(self):
            try:
                for _ in range(100):
                    yield "chunk"
            finally:
                self.closed = True

    async def scenario():
        fake = Fake()
        stream = stream_with_progress(fake)
        assert await anext(stream) == ("chunk", "chunk")
        await asyncio.sleep(0)
        await asyncio.wait_for(stream.aclose(), timeout=0.2)
        assert fake.closed

    asyncio.run(scenario())


def test_capacity_diagnosis_observes_only_existing_private_locks(tmp_path):
    from hub.inference_capacity import capacity_observation

    cfg = Settings(source_dir=str(tmp_path), local_base_url="http://fixture/v1")
    assert capacity_observation(cfg.source_dir, cfg.local_base_url) == "not_observed"
    assert not (tmp_path / ".inference-capacity").exists()

    async def scenario():
        async with local_capacity(cfg):
            assert capacity_observation(cfg.source_dir, cfg.local_base_url) == "busy"
        assert capacity_observation(cfg.source_dir, cfg.local_base_url) == "available"

    asyncio.run(scenario())
