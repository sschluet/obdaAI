"""Fixed failure diagnostics retain useful causes without exception or target disclosure."""

import json
import socket
import ssl

import httpx
import pytest
from hub.agent_failures import failure_info, failure_summary, http_read_failure
from hub.agent_schema import SchemaValidationFailure
from hub.mcp_client import MCPFailure
from pydantic import BaseModel, ValidationError

SECRET = "SYNTHETIC-PRIVATE-TOKEN"
PRIVATE = "https://private.example.invalid/api/?token=" + SECRET


def nested(inner):
    outer = httpx.ConnectError(PRIVATE)
    outer.__cause__ = inner
    return outer


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (httpx.ConnectTimeout(SECRET), "timeout"),
        (httpx.ReadTimeout(PRIVATE), "timeout"),
        (TimeoutError(SECRET), "timeout"),
        (httpx.ConnectError(PRIVATE), "connection_failed"),
        (ConnectionRefusedError(SECRET), "connection_failed"),
        (socket.gaierror(SECRET), "dns_error"),
        (nested(socket.gaierror(SECRET)), "dns_error"),
        (ssl.SSLCertVerificationError(SECRET), "tls_error"),
        (nested(ssl.SSLError(SECRET)), "tls_error"),
        (PermissionError(PRIVATE), "permission_denied"),
        (httpx.RemoteProtocolError(SECRET), "protocol_error"),
        (json.JSONDecodeError(SECRET, PRIVATE, 0), "protocol_error"),
        (ValueError(PRIVATE), "protocol_error"),
        (OSError(SECRET), "transport_error"),
        (RuntimeError(PRIVATE), "tool_error"),
    ],
)
@pytest.mark.parametrize("effect", [False, True])
def test_exception_types_give_fixed_diagnostics_without_private_text(error, category, effect):
    receipt = failure_info(error, effect)
    assert receipt["failure_category"] == category
    assert receipt["automatic_retry"] is False and receipt["effect_verified"] is False
    assert ("Nicht automatisch wiederholen" in receipt["message"]) is effect
    assert ("Lesezugriff fehlgeschlagen" in receipt["message"]) is not effect
    assert SECRET not in json.dumps(receipt) and PRIVATE not in json.dumps(receipt)


@pytest.mark.parametrize(
    ("status", "category"),
    [(401, "authentication_failed"), (403, "authorization_failed"), (404, "not_found"),
     (429, "rate_limited"), (503, "remote_unavailable"), (302, "redirect_rejected"),
     (400, "http_error")],
)
def test_http_status_diagnostics_ignore_request_response_and_exception_text(status, category):
    request = httpx.Request("GET", PRIVATE, headers={"Authorization": SECRET})
    response = httpx.Response(status, request=request, json={"private": SECRET})
    error = httpx.HTTPStatusError(SECRET, request=request, response=response)
    receipt = failure_info(error, False)
    assert receipt["failure_category"] == category and receipt["http_status"] == status
    assert receipt == http_read_failure(status)
    assert SECRET not in json.dumps(receipt) and "example.invalid" not in json.dumps(receipt)


@pytest.mark.parametrize("status", [200, 204, 299])
def test_successful_get_status_is_not_a_failure(status):
    assert http_read_failure(status) is None


@pytest.mark.parametrize("status", [True, 0, 600, "401", None])
def test_invalid_status_never_echoes_untrusted_data(status):
    assert http_read_failure(status)["failure_category"] == "protocol_error"


@pytest.mark.parametrize(
    "reason", ["timeout", "remote_tool_error", "response_limit", "schema_changed", "protocol_error"]
)
def test_mcp_existing_failure_category_is_preserved(reason):
    assert failure_info(MCPFailure(reason), False)["failure_category"] == reason


@pytest.mark.parametrize(
    "reason", ["startup_timeout", "validation_timeout", "invalid_schema", "resource_limit"]
)
def test_schema_existing_category_and_phase_are_preserved(reason):
    receipt = failure_info(SchemaValidationFailure(reason), False)
    expected = "timeout" if reason.endswith("_timeout") else "protocol_error"
    assert receipt["failure_category"] == expected
    assert receipt["failure_phase"] == "schema_" + reason


def test_mutated_reason_cannot_become_a_receipt_or_summary():
    error = MCPFailure("timeout")
    error.reason = SECRET
    assert failure_info(error, False)["failure_category"] == "protocol_error"
    schema = SchemaValidationFailure("invalid_schema")
    schema.reason = PRIVATE
    assert failure_info(schema, False)["failure_category"] == "protocol_error"
    assert SECRET not in failure_summary({"failure_category": SECRET, "message": PRIVATE})
    assert PRIVATE not in failure_summary({"failure_category": []})


def test_pydantic_validation_input_is_never_rendered():
    class Input(BaseModel):
        number: int

    with pytest.raises(ValidationError) as captured:
        Input.model_validate({"number": SECRET})
    receipt = failure_info(captured.value, False)
    assert receipt["failure_category"] == "validation_error"
    assert SECRET not in json.dumps(receipt)


def test_classification_does_not_call_exception_string_and_bounds_cyclic_causes():
    class PrivateError(RuntimeError):
        def __str__(self):
            raise AssertionError("Exception text must not be inspected")

    error = PrivateError(SECRET)
    error.__cause__ = error
    assert failure_info(error, False)["failure_category"] == "tool_error"
    outer = PrivateError(PRIVATE)
    outer.__context__ = socket.gaierror(SECRET)
    assert failure_info(outer, False)["failure_category"] == "dns_error"
