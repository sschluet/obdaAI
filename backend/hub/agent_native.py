"""Native function protocol adapter; execution remains in the canonical agent path."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from hub.agent_tools import decision_schema
from hub.policy import ContextPart

NATIVE_NO_SELECTION = "native_no_selection"
NATIVE_INVALID_ARGUMENTS = "native_invalid_arguments"


class NativeCallError(ValueError):
    """Safe protocol diagnostics, never model values or private argument paths."""

    def __init__(self, issue: str = NATIVE_INVALID_ARGUMENTS) -> None:
        self.issues = [issue]
        super().__init__("Native Werkzeugauswahl ist ungültig.")


class NativeProtocolUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Die lokale Schnittstelle unterstützt native Werkzeuge nicht.")


@dataclass(frozen=True)
class PreparedNative:
    instruction: str
    data: dict[str, Any]
    metadata: dict[str, Any]
    original_instruction: str
    original_data: dict[str, Any]


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _refs(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        if "$ref" in value:
            ref = value["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
                raise NativeCallError("schema_reference")
            result.append(ref[8:].replace("~1", "/").replace("~0", "~"))
        for key, item in value.items():
            if key != "$defs":
                result.extend(_refs(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_refs(item))
    return result


def _parameters(arguments: dict[str, Any], definitions: dict[str, Any]) -> dict[str, Any]:
    root = deepcopy(arguments)
    if set(root) == {"$ref"}:
        name = _refs(root)[0]
        if name not in definitions:
            raise NativeCallError("schema_reference")
        root = deepcopy(definitions[name])
    pending = _refs(root)
    included: dict[str, Any] = {}
    while pending:
        name = pending.pop()
        if name in included:
            continue
        if name not in definitions:
            raise NativeCallError("schema_reference")
        included[name] = deepcopy(definitions[name])
        pending.extend(_refs(definitions[name]))
    root.setdefault("type", "object")
    if included:
        root["$defs"] = included
    Draft202012Validator.check_schema(root)
    return root


def _digest(metadata: dict[str, Any]) -> str:
    return hashlib.sha256(
        _encode({key: metadata[key] for key in ("tools", "bindings")}).encode()
    ).hexdigest()


def prepare(instruction: str, data: dict[str, Any]) -> PreparedNative:
    """Compile exact existing target-scoped schemas, without mutating inputs."""
    original = deepcopy(data)
    interfaces = original["interfaces"]
    schema = decision_schema(
        [row["integration_id"] for row in interfaces],
        original["tools"],
        interfaces,
        allow_ask=original.get("allow_ask", True),
        allow_finish=original.get("allow_finish", True),
        allow_stop=original.get("allow_stop", False),
        read_only=original.get("read_only", False),
    )
    tools: list[dict[str, Any]] = []
    bindings: dict[str, Any] = {}
    targets: list[str] = []
    branches = []
    for branch in schema["anyOf"]:
        kind_schema = branch["properties"]["kind"]
        for kind in [kind_schema["const"]] if "const" in kind_schema else kind_schema["enum"]:
            branches.append((kind, branch["properties"]))
    for kind, properties in branches:
        if kind == "tool":
            identifier, tool = (
                properties["integration_id"].get("const"),
                properties["tool"].get("const"),
            )
            if not isinstance(identifier, str) or not isinstance(tool, str):
                raise NativeCallError("unbound_schema")
            if identifier not in targets:
                targets.append(identifier)
            name = f"t{targets.index(identifier)}_{tool.replace('.', '_')}"
            parameters = _parameters(properties["arguments"], schema.get("$defs", {}))
            binding = {
                "kind": kind,
                "integration_id": identifier,
                "tool": tool,
                "message": "Werkzeug am ausgewählten Ziel ausführen.",
            }
            description = (
                f"Werkzeug {tool} für integration_id={identifier}. "
                "Diese feste Zielbindung erteilt keine Rechte; "
                "nur Schema und bestehende Regeln gelten."
            )
        elif kind in {"ask", "finish", "stop"}:
            name = {"ask": "ask_user", "finish": "finish_run", "stop": "stop_run"}[kind]
            parameters = {
                "type": "object",
                "properties": {"message": deepcopy(properties["message"])},
                "required": ["message"],
                "additionalProperties": False,
            }
            binding = {"kind": kind}
            description = {
                "ask": "Tatsächlich notwendige Rückfrage.",
                "finish": "Nur bei überprüft erfülltem Ziel abschließen.",
                "stop": "Bei konkret fehlender Fähigkeit sicher anhalten.",
            }[kind]
        else:
            raise NativeCallError("unknown_schema_kind")
        if name in bindings or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise NativeCallError("function_collision")
        bindings[name] = binding
        tools.append(
            {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            }
        )
    metadata: dict[str, Any] = {"version": 1, "tools": tools, "bindings": bindings}
    metadata["sha256"] = _digest(metadata)
    native = {
        key: deepcopy(value)
        for key, value in original.items()
        if key not in {"tools", "decision_schema"}
    }
    for interface in native["interfaces"]:
        rules = interface.pop("rules", {})
        interface["policy_context"] = {
            key: value
            for key, value in rules.items()
            if key not in {"http_methods", "http_prefixes", "ha_websocket_prefixes"}
        }
    start = instruction.index("Ausgabe NUR ein JSON-Objekt nach decision_schema.")
    end = instruction.index("Öffentliche Recherche", start)
    prose = (
        instruction[:start]
        + (
            "Verwende native Funktionsaufrufe aus der bereitgestellten Liste. Der Funktionsname\n"
            "bindet Ziel und Werkzeug; arguments enthält nur Werkzeugargumente "
            "nach dessen Schema.\n"
            "Keine zusätzliche JSON-Hülle. Rückfragen über ask_user, Abschluss über finish_run,\n"
            "sicheres Anhalten über stop_run, jeweils nur soweit angeboten.\n"
            "Texte kurz und sachlich, keine internen Überlegungen.\n"
        )
        + instruction[end:]
    )
    return PreparedNative(prose, native, metadata, instruction, original)


def auxiliary_parts(metadata: dict[str, Any]) -> list[ContextPart]:
    return [
        ContextPart(content=_encode(metadata["tools"]), source_id="agent-native-tools", revision=1)
    ]


def metadata_size(metadata: dict[str, Any]) -> tuple[int, int]:
    parts = auxiliary_parts(metadata)
    return sum(len(part.content) for part in parts), sum(
        len(part.content.encode()) for part in parts
    )


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeCallError()
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise NativeCallError()


def decode_calls(metadata: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Exactly one validated native call becomes one ordinary canonical decision."""
    if not calls:
        return None
    try:
        if metadata["version"] != 1 or metadata["sha256"] != _digest(metadata) or len(calls) != 1:
            raise NativeCallError()
        call = calls[0]
        if call.get("type", "function") != "function":
            raise NativeCallError()
        function = call["function"]
        name = function["name"]
        binding = metadata["bindings"][name]
        definition = next(
            row["function"] for row in metadata["tools"] if row["function"]["name"] == name
        )
        raw = function["arguments"]
        arguments = (
            json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant)
            if isinstance(raw, str)
            else deepcopy(raw)
        )
        if not isinstance(arguments, dict):
            raise NativeCallError()
        validator = Draft202012Validator(definition["parameters"])
        if not validator.is_valid(arguments):
            if len(arguments) != 1 or next(iter(arguments)) not in {"parameters", "arguments"}:
                raise NativeCallError()
            inner = next(iter(arguments.values()))
            if not isinstance(inner, dict) or not validator.is_valid(inner):
                raise NativeCallError()
            arguments = inner
        if binding["kind"] == "tool":
            return {
                "kind": "tool",
                "integration_id": binding["integration_id"],
                "tool": binding["tool"],
                "arguments": deepcopy(arguments),
                "message": binding["message"],
            }
        return {"kind": binding["kind"], "message": arguments["message"]}
    except NativeCallError:
        raise
    except (KeyError, TypeError, ValueError, StopIteration):
        raise NativeCallError() from None
