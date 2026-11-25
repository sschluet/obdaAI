"""Bounded provider progress delivery without losing cancellation or backpressure."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing, suppress
from typing import Any

from hub.providers import Providers


async def stream_with_progress(
    provider: Any, *args: Any, **kwargs: Any
) -> AsyncIterator[tuple[str, str]]:
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=8)
    previous = provider.on_progress if isinstance(provider, Providers) else None

    def progress(phase: str) -> None:
        if not queue.full():
            queue.put_nowait(("progress", phase))

    async def consume() -> None:
        try:
            async with aclosing(provider.stream(*args, **kwargs)) as stream:
                async for chunk in stream:
                    await queue.put(("chunk", chunk))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await queue.put(("error", error))
        else:
            await queue.put(("done", None))

    if isinstance(provider, Providers):
        provider.on_progress = progress
    task = asyncio.create_task(consume())
    try:
        while True:
            kind, value = await queue.get()
            if kind == "error":
                raise value
            if kind == "done":
                return
            yield kind, value
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if isinstance(provider, Providers):
            provider.on_progress = previous
