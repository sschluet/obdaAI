"""Fixed agent failure diagnostics. Exception text and target payloads remain private."""

import json
import socket
import ssl
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from hub.agent_schema import SchemaValidationFailure
from hub.mcp_client import MCPFailure

_REASONS = {
    "authentication_failed": "Die Anmeldung am Zielsystem wurde abgewiesen.",
    "authorization_failed": "Das Zielsystem verweigert diesen Zugriff.",
    "permission_denied": "Die aktuellen Berechtigungen erlauben diesen Zugriff nicht.",
    "timeout": "Das Zielsystem hat nicht rechtzeitig geantwortet.",
    "dns_error": "Die Adresse des Zielsystems konnte nicht aufgelöst werden.",
    "tls_error": "Die sichere Verbindung zum Zielsystem konnte nicht bestätigt werden.",
    "connection_failed": "Die Verbindung zum Zielsystem konnte nicht hergestellt werden.",
    "transport_error": "Die Verbindung zum Zielsystem ist fehlgeschlagen.",
    "protocol_error": "Die Schnittstelle lieferte keine gültige Antwort.",
    "validation_error": "Der Werkzeugaufruf entspricht nicht der erlaubten Schnittstelle.",
    "not_found": "Die angefragte Schnittstelle wurde nicht gefunden.",
    "rate_limited": "Das Zielsystem begrenzt derzeit die Anzahl der Anfragen.",
    "remote_unavailable": "Das Zielsystem ist derzeit nicht verfügbar.",
    "redirect_rejected": "Eine Weiterleitung des Zielsystems wurde nicht verfolgt.",
    "http_error": "Das Zielsystem hat die Anfrage abgewiesen.",
    "remote_tool_error": "Das Zielsystem meldet einen Werkzeugfehler.",
    "response_limit": "Die Antwort überschreitet die erlaubte Größe.",
    "schema_changed": "Die freigegebene Werkzeugschnittstelle hat sich geändert.",
    "tool_error": "Der Werkzeugaufruf konnte nicht abgeschlossen werden.",
}
_MCP_REASONS = {
    "timeout", "remote_tool_error", "response_limit", "schema_changed", "protocol_error"
}
_SCHEMA_REASONS = {"startup_timeout", "validation_timeout", "invalid_schema", "resource_limit"}


def failure_summary(info: Mapping[str, Any], *, effect: bool = False) -> str:
    """Render only locally authored sentences, even for an untrusted stored receipt."""
    category = info.get("failure_category")
    reason = _REASONS.get(category, _REASONS["tool_error"]) if isinstance(category, str) else (
        _REASONS["tool_error"]
    )
    if effect:
        return "Ausführung nicht eindeutig bestätigt. " + reason + " Nicht automatisch wiederholen."
    return "Lesezugriff fehlgeschlagen. " + reason


def _receipt(category: str, effect: bool, **fields: Any) -> dict[str, Any]:
    result = {
        "failure_category": category,
        "automatic_retry": False,
        "effect_verified": False,
        **fields,
    }
    result["message"] = failure_summary(result, effect=effect)
    return result


def _http_category(status: int) -> str:
    if status == 401:
        return "authentication_failed"
    if status == 403:
        return "authorization_failed"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if 300 <= status < 400:
        return "redirect_rejected"
    if status >= 500:
        return "remote_unavailable"
    return "http_error"


def http_read_failure(status: int) -> dict[str, Any] | None:
    """Classify a GET status without consulting its URL, headers or response body."""
    if type(status) is not int or not 100 <= status <= 599:
        return _receipt("protocol_error", False)
    if 200 <= status < 300:
        return None
    return _receipt(_http_category(status), False, http_status=status)



def read_result_failure(tool: str, result: Mapping[str, Any]) -> dict[str, Any] | None:
    """Classify acknowledged read results using only fixed markers and scalar types.

    Payloads, projection diagnostics and process output never enter the receipt.
    Callers must establish that the dispatched operation was a read.
    """
    if tool == "http":
        status = result.get("http_status")
        failure = http_read_failure(status if type(status) is int else 0)
        if failure is not None:
            return failure
        if "projection_error" in result:
            return _receipt("validation_error", False, failure_phase="projection")
    elif tool == "ssh.inspect":
        status = result.get("exit_code")
        if type(status) is not int or status != 0:
            return _receipt("remote_tool_error", False)
        output = result.get("stdout")
        if type(output) is not str or len(output) > 200_000:
            return _receipt("protocol_error", False)
        lines = output.splitlines()
        marker = "OBDAAI_COMMAND_AVAILABILITY"
        if marker not in lines or sum(
            bool(line.strip()) for line in lines[:lines.index(marker)]
        ) < 3:
            return _receipt("protocol_error", False)
    elif tool == "ha.websocket" and result.get("success") is False:
        return _receipt("protocol_error", False)
    return None

def _chain(error: BaseException) -> list[BaseException]:
    """Inspect bounded exception types, never transport error strings or arguments."""
    result: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(result) < 8 and all(current is not e for e in result):
        result.append(current)
        current = current.__cause__ or current.__context__
    return result


def failure_info(error: BaseException, effect: bool) -> dict[str, Any]:
    """Safe diagnostics only; effect classification and retry authority stay with runtime."""
    if isinstance(error, MCPFailure):
        reason = getattr(error, "reason", None)
        category = (
            reason if isinstance(reason, str) and reason in _MCP_REASONS else "protocol_error"
        )
        return _receipt(category, effect)
    if isinstance(error, SchemaValidationFailure):
        reason = getattr(error, "reason", None)
        if not isinstance(reason, str) or reason not in _SCHEMA_REASONS:
            return _receipt("protocol_error", effect)
        return _receipt(
            "timeout" if reason.endswith("_timeout") else "protocol_error",
            effect,
            failure_phase="schema_" + reason,
        )
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if type(status) is int and 100 <= status <= 599:
            return _receipt(_http_category(status), effect, http_status=status)
        return _receipt("protocol_error", effect)
    chain = _chain(error)
    if any(isinstance(item, PermissionError) for item in chain):
        category = "permission_denied"
    elif any(isinstance(item, socket.gaierror) for item in chain):
        category = "dns_error"
    elif any(isinstance(item, ssl.SSLError) for item in chain):
        category = "tls_error"
    elif any(isinstance(item, (httpx.TimeoutException, TimeoutError)) for item in chain):
        category = "timeout"
    elif any(isinstance(item, (httpx.ConnectError, ConnectionError)) for item in chain):
        category = "connection_failed"
    elif isinstance(error, ValidationError):
        category = "validation_error"
    elif isinstance(error, (httpx.ProtocolError, json.JSONDecodeError, ValueError)):
        category = "protocol_error"
    elif isinstance(error, (httpx.TransportError, OSError)):
        category = "transport_error"
    else:
        category = "tool_error"
    return _receipt(category, effect)
