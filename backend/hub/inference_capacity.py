"""One bounded, cancellation-safe local inference slot across app processes.

Only an endpoint hash is persisted. No prompt, account key or model output enters
the lock. The existing private sources volume is shared by API and worker roles.
"""

import asyncio
import fcntl
import hashlib
import os
import stat
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from hub.config import Settings


class InferenceWaitTimeout(TimeoutError):
    """Safe phase code; contains no request data or endpoint."""

    def __init__(self, phase: str):
        self.phase = phase
        super().__init__("Local inference " + phase + " capacity wait exceeded")


@asynccontextmanager
async def local_capacity(
    cfg: Settings, report: Callable[[str], None] | None = None
) -> AsyncIterator[None]:
    root = Path(cfg.source_dir) / ".inference-capacity"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    meta = root.lstat()
    if (
        not stat.S_ISDIR(meta.st_mode)
        or meta.st_uid != os.getuid()
        or stat.S_IMODE(meta.st_mode) & 0o077
    ):
        raise PermissionError("Inference capacity directory is not private")
    name = hashlib.sha256(cfg.local_base_url.encode()).hexdigest() + ".lock"
    fd = os.open(root / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise PermissionError("Inference capacity lock is not private")
        started = time.monotonic()
        waiting = False
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not waiting and report:
                    report("waiting_for_model")
                waiting = True
                if time.monotonic() - started >= cfg.local_queue_timeout:
                    raise InferenceWaitTimeout("queue") from None
                await asyncio.sleep(0.05)
        if report:
            report("model_ready")
        yield
    finally:
        os.close(fd)  # Closing also releases the advisory lock after cancellation.


def capacity_observation(source_dir: str, endpoint: str) -> str:
    """Observe an existing app lock without creating files or probing inference."""
    root = Path(source_dir) / ".inference-capacity"
    try:
        meta = root.lstat()
        if (
            not stat.S_ISDIR(meta.st_mode)
            or meta.st_uid != os.getuid()
            or stat.S_IMODE(meta.st_mode) & 0o077
        ):
            return "unavailable"
        path = root / (hashlib.sha256(endpoint.encode()).hexdigest() + ".lock")
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                return "unavailable"
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return "busy"
            return "available"
        finally:
            os.close(fd)
    except FileNotFoundError:
        return "not_observed"
    except OSError:
        return "unavailable"
