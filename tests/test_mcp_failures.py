"""Fixed MCP error categories preserve bounds, authority and one-shot transport."""

import json

import httpx
import pytest
from hub.config import Settings
from hub.mcp_client import (
    MCPConnectionError,
    MCPFailure,
    MCPTransientHTTPError,
    discover,
    schema_digest,
)

SCHEMA = {
    "type": "object",
    "properties": {"uid": {"type": "integer"}},
    "required": ["uid"],
    "additionalProperties": False,
}
PRIVATE = "PRIVATE subject, credential, message identifier and URL"


@pytest.fixture
def rpc(monkeypatch):
    from hub import integration_transport

    monkeypatch.setattr(
        integration_transport, "pinned_target", lambda *_: ("http://127.0.0.1/mcp", {}, {})
    )
    calls = []

    def run(behavior, *, fail_method="tools/call", expected=None, validator=None):
        def response(request, body, result):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        def wire(request):
            body = json.loads(request.content)
            method = body["method"]
            calls.append(method)
            if method == fail_method:
                return behavior(request, body)
            if method == "initialize":
                return response(
                    request, body, {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
                )
            if method == "notifications/initialized":
                return httpx.Response(202)
            if method == "tools/list":
                return response(
                    request, body, {"tools": [{"name": "read_email", "inputSchema": SCHEMA}]}
                )
            raise AssertionError("Unexpected replay or RPC")

        with httpx.Client(transport=httpx.MockTransport(wire)) as client:
            return discover(
                client,
                Settings(),
                "http://127.0.0.1/mcp",
                "2025-11-25",
                "synthetic-token",
                configured_profile=True,
                granted_tool="read_email",
                granted_read=True,
                expected_schema=expected or schema_digest(SCHEMA),
                granted_arguments={"uid": 42},
                argument_validator=validator or (lambda *_: None),
            )

    return run, calls


def assert_safe(error, reason):
    assert isinstance(error, MCPFailure) and error.reason == reason
    assert str(error) == reason and error.args == (reason,)
    assert PRIVATE not in str(error) and PRIVATE not in repr(error)


@pytest.mark.parametrize(
    "method", ["initialize", "notifications/initialized", "tools/list", "tools/call"]
)
def test_stream_open_timeout_is_fixed_and_never_retried(rpc, method):
    run, calls = rpc

    def fail(request, _):
        raise httpx.ReadTimeout(PRIVATE, request=request)

    with pytest.raises(MCPFailure) as error:
        run(fail, fail_method=method)
    assert_safe(error.value, "timeout")
    assert calls.count(method) == 1 and calls[-1] == method
    assert error.value.__suppress_context__


def test_timeout_while_iterating_response_is_also_fixed(rpc):
    run, calls = rpc

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"jsonrpc":"2.0",'
            raise httpx.ReadTimeout(PRIVATE)

    with pytest.raises(MCPFailure) as error:
        run(
            lambda *_: httpx.Response(
                200, headers={"Content-Type": "application/json"}, stream=SlowStream()
            )
        )
    assert_safe(error.value, "timeout")
    assert calls.count("tools/call") == 1


@pytest.mark.parametrize("status", [401, 403, 500, 502, 503, 504])
def test_http_status_never_discloses_body_and_preserves_setup_marker(rpc, status):
    run, calls = rpc
    with pytest.raises(MCPFailure) as error:
        run(lambda *_: httpx.Response(status, text=PRIVATE))
    assert_safe(error.value, "protocol_error")
    assert isinstance(error.value, MCPTransientHTTPError) == (status in (502, 503))
    assert calls.count("tools/call") == 1


def test_connection_failure_retains_existing_setup_connecterror_contract(rpc):
    run, calls = rpc

    def fail(request, _):
        raise httpx.ConnectError(PRIVATE, request=request)

    with pytest.raises(MCPConnectionError) as error:
        run(fail, fail_method="initialize")
    assert isinstance(error.value, httpx.ConnectError)
    assert_safe(error.value, "protocol_error")
    assert calls == ["initialize"]
    assert_safe(MCPTransientHTTPError(PRIVATE), "protocol_error")


@pytest.mark.parametrize("rpc_error", [False, True])
def test_remote_tool_errors_do_not_retain_private_server_text(rpc, rpc_error):
    run, calls = rpc

    def fail(request, body):
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                **(
                    {"error": {"code": -32000, "message": PRIVATE}}
                    if rpc_error
                    else {
                        "result": {"isError": True, "content": [{"type": "text", "text": PRIVATE}]}
                    }
                ),
            },
        )

    with pytest.raises(MCPFailure) as error:
        run(fail)
    assert_safe(error.value, "remote_tool_error")
    assert calls.count("tools/call") == 1


@pytest.mark.parametrize("payload", ["text", "blocks", "wire"])
def test_response_size_limits_are_unchanged_and_categorized(rpc, payload):
    run, calls = rpc

    def fail(request, body):
        if payload == "wire":
            return httpx.Response(
                200, content=b"x" * 1_000_001, headers={"Content-Type": "application/json"}
            )
        content = (
            [{"type": "text", "text": "x" * 64001}]
            if payload == "text"
            else [{"type": "text", "text": ""} for _ in range(17)]
        )
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": content}}
        )

    with pytest.raises(MCPFailure) as error:
        run(fail)
    assert_safe(error.value, "response_limit")
    assert calls.count("tools/call") == 1


def test_schema_drift_stops_before_call_and_does_not_validate_or_replay(rpc):
    run, calls = rpc
    with pytest.raises(MCPFailure) as error:
        run(lambda *_: pytest.fail("Changed schema must not dispatch"), expected="f" * 64)
    assert_safe(error.value, "schema_changed")
    assert "tools/call" not in calls


def test_invalid_framing_has_fixed_protocol_category(rpc):
    run, calls = rpc
    with pytest.raises(MCPFailure) as error:
        run(
            lambda *_: httpx.Response(
                200, content=PRIVATE.encode(), headers={"Content-Type": "application/json"}
            )
        )
    assert_safe(error.value, "protocol_error")
    assert calls.count("tools/call") == 1


@pytest.mark.parametrize("typed", [False, True])
def test_schema_validator_safe_timeout_is_preserved_other_rejections_are_redacted(rpc, typed):
    run, calls = rpc

    def reject(*_):
        raise MCPFailure("timeout") if typed else ValueError(PRIVATE)

    with pytest.raises(MCPFailure) as error:
        run(lambda *_: pytest.fail("Invalid arguments must not dispatch"), validator=reject)
    assert_safe(error.value, "timeout" if typed else "protocol_error")
    assert "tools/call" not in calls


def test_exhausted_total_deadline_is_timeout_without_first_rpc(rpc, monkeypatch):
    from hub import mcp_client

    run, calls = rpc
    clock = iter([0, 21])
    monkeypatch.setattr(mcp_client.time, "monotonic", lambda: next(clock, 21))
    with pytest.raises(MCPFailure) as error:
        run(lambda *_: pytest.fail("Expired deadline must not dispatch"))
    assert_safe(error.value, "timeout")
    assert not calls


def test_failure_reason_rejects_unreviewed_text():
    with pytest.raises(ValueError) as error:
        MCPFailure(PRIVATE)  # type: ignore[arg-type]
    assert PRIVATE not in str(error.value)


@pytest.mark.parametrize(
    "reason", ["startup_timeout", "validation_timeout", "invalid_schema", "resource_limit"]
)
def test_schema_validation_failure_keeps_exact_phase_and_safe_identity(rpc, reason):
    from hub.agent_schema import SchemaValidationFailure

    run, calls = rpc
    original = SchemaValidationFailure(reason)

    def reject(*_):
        raise original

    with pytest.raises(SchemaValidationFailure) as error:
        run(lambda *_: pytest.fail("Failed validation must never call the tool"), validator=reject)
    assert error.value is original
    assert error.value.reason == reason
    assert PRIVATE not in str(error.value)
    assert "tools/call" not in calls
