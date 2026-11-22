"""Read receipts must not mistake unusable HTTP data or failed inspection for success."""

import json
import subprocess

import pytest
from hub.agent_failures import http_read_failure, read_result_failure
from hub.agent_tools import SSH_INSPECT

SECRET = "SYNTHETIC-PRIVATE-READ-RESULT"
PRIVATE = "https://private.example.invalid/?credential=" + SECRET


def assert_private_safe(receipt, category):
    assert receipt["failure_category"] == category
    assert receipt["automatic_retry"] is False
    assert receipt["effect_verified"] is False
    assert receipt["message"].startswith("Lesezugriff fehlgeschlagen.")
    serialized = json.dumps(receipt)
    assert SECRET not in serialized and PRIVATE not in serialized
    assert "stdout" not in receipt and "error" not in receipt and "body" not in receipt


@pytest.mark.parametrize("status", [200, 204, 299])
@pytest.mark.parametrize("marker", [SECRET, "", False, None, {"private": PRIVATE}])
def test_http_success_with_any_projection_error_marker_is_failed(status, marker):
    receipt = read_result_failure("http", {
        "http_status": status, "projection_error": marker,
        "body": {"credential": SECRET}, "url": PRIVATE,
    })
    assert_private_safe(receipt, "validation_error")
    assert receipt["failure_phase"] == "projection"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503, 302, 400, True, 0, 600, "200", None])
def test_http_status_failure_precedes_projection_diagnostic(status):
    receipt = read_result_failure("http", {
        "http_status": status, "projection_error": PRIVATE, "body": SECRET,
    })
    assert receipt == http_read_failure(status)
    assert_private_safe(receipt, receipt["failure_category"])


@pytest.mark.parametrize("status", [200, 204, 299])
def test_http_success_without_projection_error_remains_successful(status):
    assert read_result_failure("http", {"http_status": status, "body": SECRET}) is None


@pytest.mark.parametrize("status", [1, -1, 255, True, False, "0", 0.0, None, [], {}])
def test_failed_or_invalid_ssh_exit_is_not_a_successful_inspection(status):
    receipt = read_result_failure("ssh.inspect", {
        "exit_code": status, "stdout": PRIVATE, "stderr": SECRET,
    })
    assert_private_safe(receipt, "remote_tool_error")
    assert "exit_code" not in receipt


def test_missing_ssh_exit_is_failed_and_exact_zero_is_successful():
    assert_private_safe(read_result_failure("ssh.inspect", {}), "remote_tool_error")
    assert read_result_failure("ssh.inspect", {"exit_code": 0,
        "stdout": "Linux\nuser\nup\nOBDAAI_COMMAND_AVAILABILITY\n"}) is None


def test_websocket_negative_read_acknowledgement_is_failed_without_error_text():
    receipt = read_result_failure("ha.websocket", {
        "success": False, "error": {"code": PRIVATE, "message": SECRET},
    })
    assert_private_safe(receipt, "protocol_error")
    assert read_result_failure("ha.websocket", {"response": {"private": SECRET}}) is None
    assert read_result_failure("ha.websocket", {"success": True}) is None


def test_classifier_never_formats_or_truth_tests_private_marker_objects():
    class PrivateValue:
        def __bool__(self):
            raise AssertionError("Do not interpret untrusted result prose")

        def __str__(self):
            raise AssertionError("Do not render untrusted result prose")

    marker = PrivateValue()
    assert_private_safe(read_result_failure("http", {
        "http_status": 200, "projection_error": marker,
    }), "validation_error")
    assert_private_safe(read_result_failure("http", {"http_status": marker}), "protocol_error")
    assert_private_safe(read_result_failure("ssh.inspect", {"exit_code": marker}),
                        "remote_tool_error")


def test_classifier_does_not_invent_semantics_for_other_tool_results():
    assert read_result_failure("mcp.catalog", {"success": False, "error": SECRET}) is None


@pytest.mark.parametrize("failed_index", [0, 1, 2])
def test_fixed_ssh_inspection_stops_when_a_required_initial_command_fails(failed_index):
    assert SSH_INSPECT.startswith("set -e\n")
    required = ["/usr/bin/uname -sr", "/usr/bin/id -un", "/usr/bin/uptime"]
    prefix = SSH_INSPECT.split("if [ -x", 1)[0]
    for index, command in enumerate(required):
        assert command in prefix
        prefix = prefix.replace(command, "false" if index == failed_index else "true")
    result = subprocess.run(["/bin/sh", "-c", prefix + "printf 'MASKED-FAILURE'\n"],
                            text=True, capture_output=True, check=False)
    assert result.returncode != 0 and "MASKED-FAILURE" not in result.stdout


@pytest.mark.parametrize("output", [None, True, 0, [], {}, SECRET,
    "OBDAAI_COMMAND_AVAILABILITY\n", "Linux\nuser\nOBDAAI_COMMAND_AVAILABILITY\n",
    "Linux\nuser\nup\nprefixOBDAAI_COMMAND_AVAILABILITY\n",
    "\n\n\nOBDAAI_COMMAND_AVAILABILITY\n",
    "Linux\nuser\nup\nOBDAAI_COMMAND_AVAILABILITY\n" + "x" * 200_000])
def test_zero_ssh_exit_requires_a_bounded_complete_fixed_inspection(output):
    assert_private_safe(read_result_failure("ssh.inspect", {"exit_code": 0, "stdout": output}),
                        "protocol_error")


def test_zero_ssh_exit_does_not_convert_or_truth_test_private_output():
    class PrivateOutput:
        def __str__(self):
            raise AssertionError("Do not stringify SSH output")

        def __bool__(self):
            raise AssertionError("Do not truth-test SSH output")

    assert_private_safe(read_result_failure("ssh.inspect", {
        "exit_code": 0, "stdout": PrivateOutput(), "stderr": SECRET,
    }), "protocol_error")
