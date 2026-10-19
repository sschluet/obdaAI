"""Isolated real-process checks of untrusted MCP schema resource boundaries."""

import json
import signal
import subprocess
import sys

import pytest
from hub.agent_schema import validate


def child(schema, arguments, *, startup=""):
    program = startup + "\nimport runpy; runpy.run_module('hub.agent_schema', run_name='__main__')"
    return subprocess.run(
        [sys.executable, "-I", "-c", program],
        input=json.dumps({"schema": schema, "arguments": arguments}).encode(),
        capture_output=True,
        # These direct child checks exercise CPU limits independently of CI
        # scheduling. The actual parent's unchanged three-second cap is tested
        # separately below.
        timeout=10,
    )


def test_valid_schema_survives_more_than_one_second_of_trusted_startup_cpu():
    result = child(
        {"type": "object", "properties": {}},
        {},
        startup="""
import time
started = time.process_time()
while time.process_time() - started < 1.1:
    pass
""",
    )
    assert result.returncode == 0, result.stderr


def test_pathological_untrusted_regex_still_hits_cpu_limit():
    result = child(
        {"type": "object", "properties": {"text": {"type": "string", "pattern": "(a+)+$"}}},
        {"text": "a" * 50 + "!"},
    )
    assert result.returncode in (-signal.SIGPROF, -signal.SIGKILL, -signal.SIGXCPU)


def test_untrusted_cpu_timer_enforces_budget_independently_of_lifetime_hard_cap():
    result = child(
        {"type": "object", "properties": {"text": {"type": "string", "pattern": "(a+)+$"}}},
        {"text": "a" * 50 + "!"},
        startup="""
import resource
original_setrlimit = resource.setrlimit
def without_lifetime_cpu_cap(which, limits):
    if which != resource.RLIMIT_CPU:
        original_setrlimit(which, limits)
resource.setrlimit = without_lifetime_cpu_cap
""",
    )
    # Only this test child suppresses the redundant rounded lifetime CPU cap.
    # Without the one-second profiling timer, the outer watchdog must fail the
    # test instead of accepting a later hard-limit signal as equivalent.
    assert result.returncode == -signal.SIGPROF


def test_inherited_finite_cpu_hard_limit_is_not_raised():
    result = child(
        {"type": "object"},
        {},
        startup="""
import resource
resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
""",
    )
    # A local import may itself exhaust this inherited cap; it must never be
    # silently raised to make validation succeed.
    assert result.returncode in (0, -signal.SIGKILL, -signal.SIGXCPU)


@pytest.mark.parametrize(
    "schema,arguments",
    [
        ({"type": "not-a-json-schema-type"}, {}),
        ({"type": "object", "required": ["missing"]}, {}),
        ({"$ref": "https://example.test/private-schema"}, {}),
        ({"$ref": "file:///etc/passwd"}, {}),
    ],
)
def test_invalid_schema_arguments_and_external_references_fail(schema, arguments):
    result = child(schema, arguments)
    assert result.returncode == 2
    assert not result.stdout and not result.stderr


def test_parent_validation_remains_bounded_at_three_seconds(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 3
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr("hub.agent_schema.subprocess.run", timeout)
    with pytest.raises(ValueError, match="validation time limit"):
        validate({"type": "object"}, {})
