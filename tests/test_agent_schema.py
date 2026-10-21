"""Isolated real-process checks of untrusted MCP schema resource boundaries."""

import json
import signal
import subprocess
import sys

import pytest
from hub import agent_schema
from hub.agent_schema import SchemaValidationFailure, validate


def child(schema, arguments, *, startup=""):
    program = startup + "\nimport runpy; runpy.run_module('hub.agent_schema', run_name='__main__')"
    return subprocess.run(
        [sys.executable, "-I", "-c", program],
        input=json.dumps({"schema": schema, "arguments": arguments}).encode(),
        capture_output=True,
        # Direct child checks exercise CPU limits independently of scheduling.
        # The parent separately bounds startup and untrusted validation below.
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


def controlled_child(monkeypatch, program):
    original = subprocess.Popen

    def start(*args, **kwargs):
        assert args[0][-1] == "--ready"
        return original([sys.executable, "-I", "-c", program], **kwargs)

    monkeypatch.setattr(agent_schema.subprocess, "Popen", start)


def test_trusted_startup_does_not_consume_untrusted_validation_budget(monkeypatch):
    monkeypatch.setattr(agent_schema, "STARTUP_SECONDS", 3)
    monkeypatch.setattr(agent_schema, "VALIDATION_SECONDS", 0.1)
    controlled_child(monkeypatch, """
import sys,time,json
time.sleep(0.2)
sys.stdout.buffer.write(b'READY\\n');sys.stdout.buffer.flush()
assert json.loads(sys.stdin.buffer.read())['arguments']=={}
""")
    validate({"type": "object"}, {})


@pytest.mark.parametrize("phase", ["startup", "validation"])
def test_parent_kills_and_reaps_child_at_each_fixed_wall_limit(monkeypatch, phase):
    monkeypatch.setattr(agent_schema, "STARTUP_SECONDS", 0.2 if phase == "startup" else 3)
    monkeypatch.setattr(agent_schema, "VALIDATION_SECONDS", 0.2)
    controlled_child(monkeypatch, """
import sys,time
""" + ("sys.stdout.buffer.write(b'READY\\n');sys.stdout.buffer.flush()\n"
       if phase == "validation" else "") + "time.sleep(30)\n")
    with pytest.raises(SchemaValidationFailure) as caught:
        validate({"type": "object"}, {})
    assert caught.value.reason == phase + "_timeout"
    assert agent_schema.VALIDATION_SECONDS == 0.2


def test_parent_rejects_invalid_readiness_without_sending_private_arguments(monkeypatch):
    controlled_child(monkeypatch, """
import sys
sys.stdout.buffer.write(b'WRONG\\n');sys.stdout.buffer.flush()
# The parent must kill us rather than supplying arguments after a bad handshake.
assert not sys.stdin.buffer.read()
""")
    with pytest.raises(SchemaValidationFailure, match="invalid_schema"):
        validate({"type": "object"}, {"private": "never send before ready"})


def test_parent_real_validation_preserves_schema_and_external_ref_checks():
    assert agent_schema.STARTUP_SECONDS == 10 and agent_schema.VALIDATION_SECONDS == 3
    validate({"type": "object", "required": ["ok"]}, {"ok": True})
    for schema in ({"required": ["missing"]}, {"$ref": "https://example.test/no-network"}):
        with pytest.raises(SchemaValidationFailure, match="invalid_schema"):
            validate(schema, {})
