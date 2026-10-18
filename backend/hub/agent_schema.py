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
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except (ValueError, OSError):
        pass  # CPU and parent wall-clock limits still apply on Darwin.
    import jsonschema  # type: ignore[import-untyped]
    from referencing import Registry

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
