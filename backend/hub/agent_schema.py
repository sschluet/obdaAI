"""Complete MCP JSON Schema validation in a bounded, network-free child process."""

import json
import subprocess
import sys
from typing import Any


def validate(schema: dict[str, Any], arguments: Any) -> None:
    payload = json.dumps({"schema": schema, "arguments": arguments}, allow_nan=False).encode()
    if len(payload) > 300_000 or len(json.dumps(schema)) > 128_000:
        raise ValueError("MCP schema or argument limit")
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-m", "hub.agent_schema"],
            input=payload,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("MCP schema validation time limit") from None
    if result.returncode != 0:
        raise ValueError("MCP arguments do not satisfy the current schema")


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
