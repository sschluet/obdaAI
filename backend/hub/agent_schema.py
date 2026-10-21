"""Complete MCP JSON Schema validation in a bounded, network-free child process."""

import json
import os
import select
import subprocess
import sys
import time
from typing import Any

STARTUP_SECONDS = 10
VALIDATION_SECONDS = 3
READY = b"READY\n"


class SchemaValidationFailure(ValueError):
    """Fixed diagnostic reason; never includes schemas, arguments or child output."""

    def __init__(self, reason: str) -> None:
        if reason not in {
            "startup_timeout", "validation_timeout", "invalid_schema", "resource_limit"
        }:
            raise ValueError("Unknown schema failure category")
        self.reason = reason
        super().__init__(reason)


def validate(schema: dict[str, Any], arguments: Any) -> None:
    payload = json.dumps({"schema": schema, "arguments": arguments}, allow_nan=False).encode()
    if len(payload) > 300_000 or len(json.dumps(schema)) > 128_000:
        raise ValueError("MCP schema or argument limit")
    with subprocess.Popen(
        [sys.executable, "-I", "-m", "hub.agent_schema", "--ready"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as child:
        assert child.stdout is not None
        try:
            deadline = time.monotonic() + STARTUP_SECONDS
            received = b""
            # Untrusted schema/arguments are withheld until trusted imports and
            # resource limits are ready. Startup never consumes their budget.
            while len(received) < len(READY):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([child.stdout], [], [], remaining)[0]:
                    raise SchemaValidationFailure("startup_timeout")
                chunk = os.read(child.stdout.fileno(), len(READY) - len(received))
                if not chunk:
                    raise SchemaValidationFailure("resource_limit")
                received += chunk
            if received != READY:
                raise SchemaValidationFailure("invalid_schema")
            try:
                child.communicate(payload, timeout=VALIDATION_SECONDS)
            except subprocess.TimeoutExpired:
                raise SchemaValidationFailure("validation_timeout") from None
            if child.returncode != 0:
                raise SchemaValidationFailure(
                    "resource_limit" if child.returncode is not None and child.returncode < 0
                    else "invalid_schema"
                )
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate()


def main() -> None:
    import math
    import resource
    import signal

    try:
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except (ValueError, OSError):
        pass  # CPU and parent wall-clock limits still apply on Darwin.
    import jsonschema  # type: ignore[import-untyped]
    from referencing import Registry

    # RLIMIT_CPU measures lifetime CPU, including trusted interpreter/import
    # startup. Give untrusted parsing/validation its own one-second CPU timer;
    # retain a rounded lifetime hard stop without relaxing inherited limits.
    usage = resource.getrusage(resource.RUSAGE_SELF)
    lifetime_limit = math.ceil(usage.ru_utime + usage.ru_stime + 1)
    inherited_soft, inherited_hard = resource.getrlimit(resource.RLIMIT_CPU)
    hard = (
        lifetime_limit
        if inherited_hard == resource.RLIM_INFINITY
        else min(lifetime_limit, inherited_hard)
    )
    soft = hard if inherited_soft == resource.RLIM_INFINITY else min(hard, inherited_soft)
    resource.setrlimit(resource.RLIMIT_CPU, (soft, hard))
    signal.signal(signal.SIGPROF, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_PROF, 1)

    if sys.argv[1:] == ["--ready"]:
        sys.stdout.buffer.write(READY)
        sys.stdout.buffer.flush()

    value = json.loads(sys.stdin.buffer.read(300_001))
    schema = value["schema"]
    validator = jsonschema.validators.validator_for(schema)
    validator.check_schema(schema)
    # Explicit empty registry: no file/HTTP retrieval, including external $refs.
    validator(schema, registry=Registry()).validate(value["arguments"])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(2)
