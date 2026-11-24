"""Native function protocol adapter; execution remains in the canonical agent path."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from itertools import islice
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from hub.agent_tools import decision_schema
from hub.policy import ContextPart

NATIVE_NO_SELECTION = "native_no_selection"
NATIVE_INVALID_ARGUMENTS = "native_invalid_arguments"


class NativeCallError(ValueError):
    """Safe protocol diagnostics, never model values or private argument paths."""

    def __init__(self, issue: str | list[str] = NATIVE_INVALID_ARGUMENTS) -> None:
        candidates = [issue] if isinstance(issue, str) else issue
        self.issues = list(
            dict.fromkeys(
                value
                if re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value)
                else NATIVE_INVALID_ARGUMENTS
                for value in candidates
            )
        )[:6] or [NATIVE_INVALID_ARGUMENTS]
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


def _single_anyof(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten a sole conjunct only when sibling interactions stay identical."""
    variants = schema.get("anyOf")
    if not isinstance(variants, list) or len(variants) != 1 or not isinstance(variants[0], dict):
        return schema
    branch = variants[0]
    if any(
        key in schema or key in branch
        for key in ("$id", "$anchor", "$dynamicAnchor", "$dynamicRef")
    ):
        return schema
    harmless = {
        "type",
        "$defs",
        "$schema",
        "title",
        "description",
        "default",
        "examples",
        "$comment",
    }
    for key, value in schema.items():
        if key == "anyOf":
            continue
        if key in branch:
            if branch[key] != value:
                return schema
        if key not in harmless:
            # Even identical additionalProperties:false at both levels can
            # constrain different property sets. Preserve those conjunctions.
            return schema
    return {**{key: value for key, value in schema.items() if key != "anyOf"}, **deepcopy(branch)}


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
    root = _single_anyof(root)
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
            canonical = _parameters(properties["arguments"], schema.get("$defs", {}))
            definitions = canonical.pop("$defs", None)
            # A fixed object property lets native parsers preserve nested JSON
            # types even when the canonical root is an anyOf/ref schema.
            canonical["type"] = "object"
            parameters = {
                "type": "object",
                "additionalProperties": False,
                "properties": {"arguments": canonical},
                "required": ["arguments"],
                **({"$defs": definitions} if definitions is not None else {}),
            }
            Draft202012Validator.check_schema(parameters)
            binding = {
                "kind": kind,
                "integration_id": identifier,
                "tool": tool,
                "argument_object": True,
                "message": "Werkzeug am ausgewählten Ziel ausführen.",
            }
            description = (
                f"Werkzeug {tool} für integration_id={identifier}. "
                "Diese feste Zielbindung erteilt keine Rechte; "
                "nur Schema und bestehende Regeln gelten."
            )
            null_fields = [
                key
                for key, value in canonical.get("properties", {}).items()
                if isinstance(value, dict)
                and value.get("type") == "null"
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key)
            ]
            if null_fields:
                description += " Felder mit type:null: " + ", ".join(null_fields[:6]) + "."
                description += " Nicht benötigte optionale Felder dürfen entfallen."
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
            "Wähle pro Planungsschritt GENAU EINEN Funktionsaufruf. Warte dessen Ergebnis ab; "
            "keine parallelen Aufrufe. Abschluss nur aus bereits vorliegenden Belegen.\n"
            "Verwende native Funktionsaufrufe aus der bereitgestellten Liste. Der Funktionsname\n"
            "bindet Ziel und Werkzeug. Werkzeugfunktionen erhalten genau den Parameter "
            "arguments als vollständiges JSON-Objekt nach dessen Schema, keine JSON-Zeichenkette.\n"
            "ask_user, finish_run und stop_run erhalten direkt message.\n"
            "Beachte die Feldtypen genau: type:null verlangt JSON-null, kein Objekt oder Text. "
            "Nicht benötigte optionale Felder dürfen entfallen.\n"
            "Keine zusätzliche JSON-Hülle. Rückfragen über ask_user, Abschluss über finish_run,\n"
            "sicheres Anhalten über stop_run, jeweils nur soweit angeboten.\n"
            "Texte kurz und sachlich, keine internen Überlegungen.\n"
        )
        + instruction[end:]
    )
    return PreparedNative(prose, native, metadata, instruction, original)


def native_messages(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Validated model-view history; never a source of execution authority."""
    if "messages" not in metadata:
        if "messages_sha256" in metadata:
            raise NativeCallError("native_history_hash")
        return []
    try:
        messages = metadata["messages"]
        if (
            metadata.get("version") != 1
            or metadata.get("sha256") != _digest(metadata)
            or not isinstance(messages, list)
            or metadata.get("messages_sha256")
            != hashlib.sha256(_encode(messages).encode()).hexdigest()
        ):
            raise NativeCallError("native_history_hash")
    except NativeCallError:
        raise
    except (KeyError, TypeError, ValueError):
        raise NativeCallError("native_history_hash") from None
    pending: tuple[str, dict[str, Any], int] | None = None
    seen: set[str] = set()
    last_sequence = 0
    try:
        for message in messages:
            if not isinstance(message, dict):
                raise NativeCallError("native_history_envelope")
            if message.get("role") == "assistant":
                if (
                    pending is not None
                    or set(message) != {"role", "content", "tool_calls"}
                    or message["content"] is not None
                    or len(message["tool_calls"]) != 1
                ):
                    raise NativeCallError("native_history_pair")
                call = message["tool_calls"][0]
                if set(call) != {"id", "type", "function"} or call["type"] != "function":
                    raise NativeCallError("native_history_envelope")
                identifier = call["id"]
                if (
                    not isinstance(identifier, str)
                    or not re.fullmatch(r"call_obdaai_[1-9][0-9]{0,9}", identifier)
                    or identifier in seen
                ):
                    raise NativeCallError("native_history_id")
                sequence = int(identifier.removeprefix("call_obdaai_"))
                if sequence <= last_sequence or set(call["function"]) != {"name", "arguments"}:
                    raise NativeCallError("native_history_id")
                decision = decode_calls(metadata, [call])
                if decision is None or decision["kind"] != "tool":
                    raise NativeCallError("native_history_binding")
                seen.add(identifier)
                pending = (identifier, decision, sequence)
                last_sequence = sequence
            elif message.get("role") == "tool":
                if (
                    pending is None
                    or set(message) != {"role", "tool_call_id", "content"}
                    or message["tool_call_id"] != pending[0]
                    or not isinstance(message["content"], str)
                ):
                    raise NativeCallError("native_history_pair")
                result = json.loads(
                    message["content"], object_pairs_hook=_object, parse_constant=_invalid_constant
                )
                receipt = result.get("_obdaai_receipt") if isinstance(result, dict) else None
                if (
                    not isinstance(receipt, dict)
                    or set(receipt)
                    != {"sequence", "kind", "status", "integration_id", "tool", "model_view_only"}
                    or type(receipt["sequence"]) is not int
                    or receipt["sequence"] != pending[2]
                    or receipt["kind"] not in {"read", "effect"}
                    or receipt["status"] not in {"succeeded", "failed"}
                    or receipt["integration_id"] != pending[1]["integration_id"]
                    or receipt["tool"] != pending[1]["tool"]
                    or receipt["model_view_only"] is not True
                ):
                    raise NativeCallError("native_history_receipt")
                pending = None
            else:
                # Controller feedback remains in the ordinary bounded user JSON;
                # source/model text is never promoted to free-standing messages.
                raise NativeCallError("native_history_role")
        if pending is not None:
            raise NativeCallError("native_history_pair")
    except NativeCallError:
        raise
    except (KeyError, TypeError, ValueError, IndexError):
        raise NativeCallError("native_history_envelope") from None
    return deepcopy(messages)


def with_history(
    prepared: PreparedNative,
    fitted: dict[str, Any],
) -> tuple[PreparedNative, dict[str, Any]]:
    """Translate only fitted, executed and currently schema-bound observations."""
    model_data = deepcopy(fitted)
    metadata = deepcopy(prepared.metadata)
    metadata.pop("messages", None)
    metadata.pop("messages_sha256", None)
    history = model_data.get("history", [])
    if not isinstance(history, list):
        raise NativeCallError("native_history_envelope")
    counts: dict[int, int] = {}
    for entry in history:
        if isinstance(entry, dict) and type(entry.get("sequence")) is int:
            sequence = entry["sequence"]
            counts[sequence] = counts.get(sequence, 0) + 1
    messages: list[dict[str, Any]] = []
    retained = []
    converted: set[int] = set()
    last_sequence = 0
    for entry in history:
        if not isinstance(entry, dict):
            retained.append(entry)
            continue
        sequence, document, result = (
            entry.get("sequence"),
            entry.get("document"),
            entry.get("result"),
        )
        if (
            type(sequence) is not int
            or not 0 < sequence < 10**10
            or counts.get(sequence) != 1
            or sequence <= last_sequence
            or entry.get("kind") not in {"read", "effect"}
            or entry.get("status") not in {"succeeded", "failed"}
            or not isinstance(document, dict)
            or not isinstance(result, dict)
            or "_obdaai_receipt" in result
            or not isinstance(document.get("arguments"), dict)
        ):
            retained.append(entry)
            continue
        name = next(
            (
                name
                for name, binding in metadata["bindings"].items()
                if binding.get("kind") == "tool"
                and binding.get("integration_id") == document.get("integration_id")
                and binding.get("tool") == document.get("tool")
            ),
            None,
        )
        if name is None:
            retained.append(entry)
            continue
        arguments = document["arguments"]
        wire = (
            {"arguments": arguments}
            if metadata["bindings"][name].get("argument_object")
            else arguments
        )
        call = {
            "id": f"call_obdaai_{sequence}",
            "type": "function",
            "function": {"name": name, "arguments": _encode(wire)},
        }
        try:
            decision = decode_calls(metadata, [call])
            # No normalization or invented defaults may rewrite an executed call.
            if decision is None or _encode(decision.get("arguments")) != _encode(arguments):
                raise NativeCallError("native_history_arguments")
        except NativeCallError:
            retained.append(entry)
            continue
        receipt = {
            "sequence": sequence,
            "kind": entry["kind"],
            "status": entry["status"],
            "integration_id": document["integration_id"],
            "tool": document["tool"],
            "model_view_only": True,
        }
        messages.extend(
            [
                {"role": "assistant", "content": None, "tool_calls": [call]},
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": _encode({**result, "_obdaai_receipt": receipt}),
                },
            ]
        )
        converted.add(sequence)
        last_sequence = sequence
    if messages:
        metadata["messages"] = messages
        metadata["messages_sha256"] = hashlib.sha256(_encode(messages).encode()).hexdigest()
        native_messages(metadata)
        model_data["history"] = retained
        latest = model_data.get("latest_observation")
        if isinstance(latest, dict) and latest.get("sequence") in converted:
            # The tool message carries the result. Keep independently derived
            # shape/semantic summaries, hashes and status for large observations.
            model_data["latest_observation"] = {
                key: value for key, value in latest.items() if key != "result"
            }
    return PreparedNative(
        prepared.instruction,
        deepcopy(model_data),
        metadata,
        prepared.original_instruction,
        deepcopy(prepared.original_data),
    ), model_data


def auxiliary_parts(metadata: dict[str, Any]) -> list[ContextPart]:
    parts = [
        ContextPart(content=_encode(metadata["tools"]), source_id="agent-native-tools", revision=1)
    ]
    messages = native_messages(metadata)
    if messages:
        parts.append(
            ContextPart(content=_encode(messages), source_id="agent-native-history", revision=1)
        )
    return parts


def metadata_size(metadata: dict[str, Any]) -> tuple[int, int]:
    parts = auxiliary_parts(metadata)
    return sum(len(part.content) for part in parts), sum(
        len(part.content.encode()) for part in parts
    )


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeCallError("native_duplicate_json_keys")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise NativeCallError("native_invalid_json")


def _schema_issues(validator: Any, arguments: Any) -> list[str]:
    """Only schema-owned vocabulary; never messages, instance keys or paths."""
    generic: list[str] = []
    field_types: dict[str, set[str]] = {}
    pending = deque((error, True) for error in islice(validator.iter_errors(arguments), 32))
    known_types = {"array", "boolean", "integer", "null", "number", "object", "string"}
    inspected = 0
    while pending and inspected < 256:
        error, type_applicable = pending.popleft()
        inspected += 1
        keyword = error.validator
        if keyword == "type" and type_applicable:
            path = list(error.absolute_schema_path)
            fields = [
                path[index + 1]
                for index, value in enumerate(path[:-1])
                if value == "properties"
                and isinstance(path[index + 1], str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", path[index + 1])
            ]
            expected = error.schema.get("type")
            choices = [expected] if isinstance(expected, str) else expected
            parent = error.parent
            relative = list(error.schema_path)
            if (
                parent is not None
                and parent.validator in {"anyOf", "oneOf"}
                and len(relative) == 2
                and relative[-1] == "type"
            ):
                # A nullable/union alternative alone is not the field contract.
                # Union all schema-owned branch types, or omit the detail if
                # these types cannot be established without further inference.
                union: set[str] = set()
                for shape in parent.schema.get(parent.validator, []):
                    for _ in range(8):
                        ref = shape.get("$ref") if isinstance(shape, dict) else None
                        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
                            break
                        shape = validator.schema.get("$defs", {}).get(ref[8:])
                    kind = shape.get("type") if isinstance(shape, dict) else None
                    types = [kind] if isinstance(kind, str) else kind
                    if (
                        not isinstance(types, list)
                        or not types
                        or any(
                            not isinstance(item, str) or item not in known_types for item in types
                        )
                    ):
                        union.clear()
                        break
                    union.update(types)
                choices = sorted(union)
            if (
                fields
                and isinstance(choices, list)
                and choices
                and all(isinstance(value, str) and value in known_types for value in choices)
            ):
                field = fields[-1]
                property_index = max(
                    index
                    for index, value in enumerate(path[:-1])
                    if value == "properties" and path[index + 1] == fields[-1]
                )
                tail = path[property_index + 2 :]
                if any(key in tail for key in ("additionalProperties", "patternProperties")):
                    field += ".value"
                elif any(key in tail for key in ("items", "prefixItems", "additionalItems")):
                    field += ".item"
                field_types.setdefault(field, set()).update(choices)
        if keyword in Draft202012Validator.VALIDATORS:
            value = "schema:" + keyword
            if value not in generic:
                generic.append(value)
        if keyword == "required" and isinstance(error.instance, dict):
            for field in error.schema.get("required", []):
                if (
                    isinstance(field, str)
                    and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", field)
                    and field not in error.instance
                ):
                    value = "required:" + field
                    if value not in generic and len(generic) < 6:
                        generic.append(value)
        # Context diagnostics are bounded and remain schema-owned. Never use
        # error.message/path/instance to form field names or copy actual values.
        children = list(islice(error.context, 128))
        relevant = None
        if keyword in {"anyOf", "oneOf"} and isinstance(error.instance, dict):
            variants = error.schema.get(keyword, [])
            relevant = set()
            for index, variant in enumerate(variants):
                if not isinstance(variant, dict):
                    relevant.add(index)
                    continue
                matches = True
                for key, shape in variant.get("properties", {}).items():
                    if key not in error.instance or not isinstance(shape, dict):
                        continue
                    options = [shape["const"]] if "const" in shape else shape.get("enum")
                    if isinstance(options, list) and not any(
                        _encode(error.instance[key]) == _encode(choice) for choice in options
                    ):
                        matches = False
                        break
                if matches:
                    relevant.add(index)
        # Keep generic/missing-field evidence even for a nonmatching variant;
        # only named TYPE hints must not imply that variant's type contract.
        pending.extend(
            (
                child,
                type_applicable
                and (
                    relevant is None or bool(child.schema_path) and child.schema_path[0] in relevant
                ),
            )
            for child in children
        )
    specific = []
    for field, types in field_types.items():
        hint = "_or_".join(sorted(types))
        value = "schema_type:" + field + ":" + hint
        specific.append(value if len(value) <= 120 else "schema_type:" + field + ":union")
    return ["args_schema_invalid", *(specific + generic)[:5]]


def decode_calls(metadata: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Exactly one validated native call becomes one ordinary canonical decision."""
    if not calls:
        return None
    try:
        if len(calls) != 1:
            raise NativeCallError("native_call_count")
        if metadata["version"] != 1 or metadata["sha256"] != _digest(metadata):
            raise NativeCallError("native_metadata_invalid")
        call = calls[0]
        if call.get("type", "function") != "function":
            raise NativeCallError("native_call_envelope_invalid")
        function = call["function"]
        name = function["name"]
        if not isinstance(name, str) or name not in metadata["bindings"]:
            raise NativeCallError("native_unknown_function")
        binding = metadata["bindings"][name]
        definition = next(
            row["function"] for row in metadata["tools"] if row["function"]["name"] == name
        )
        raw = function["arguments"]
        try:
            arguments = (
                json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant)
                if isinstance(raw, str)
                else deepcopy(raw)
            )
        except json.JSONDecodeError:
            raise NativeCallError("native_invalid_json") from None
        canonical = deepcopy(definition["parameters"])
        if binding.get("argument_object") is True:
            canonical = deepcopy(definition["parameters"]["properties"]["arguments"])
            if "$defs" in definition["parameters"]:
                canonical["$defs"] = deepcopy(definition["parameters"]["$defs"])
        validator = Draft202012Validator(canonical)
        if not isinstance(arguments, dict):
            raise NativeCallError(_schema_issues(validator, arguments))
        if not validator.is_valid(arguments):
            if (
                not isinstance(arguments, dict)
                or len(arguments) != 1
                or next(iter(arguments)) not in {"parameters", "arguments"}
            ):
                raise NativeCallError(_schema_issues(validator, arguments))
            inner = next(iter(arguments.values()))
            if not isinstance(inner, dict) or not validator.is_valid(inner):
                raise NativeCallError(_schema_issues(validator, inner))
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
        raise NativeCallError("native_call_envelope_invalid") from None
