"""Model-active HTTP operations; private original schemas remain authoritative."""

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from hub.agent_tools import HTTPCall, Projection

_FLAT = {"items_path", "fields", "limit", "filter_mode", "filter_field", "filter_value"}


def canonical_arguments(binding: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    kind = binding["http_facade"]
    if kind == "read":
        return {"method": "GET", **deepcopy(arguments)}
    if kind == "change":
        return deepcopy(arguments)
    if kind != "project":
        raise ValueError("Unknown HTTP wire view")
    result = {k: deepcopy(v) for k, v in arguments.items() if k not in _FLAT}
    projection = {
        key: deepcopy(
            arguments.get(
                key,
                Projection.model_fields[key].get_default(
                    call_default_factory=True,
                ),
            )
        )
        for key in ("items_path", "fields", "limit")
    }
    mode, field, value = (arguments[key] for key in ("filter_mode", "filter_field", "filter_value"))
    projection.update(
        where_pointer=None if mode == "none" else field,
        where_equals=deepcopy(value) if mode == "equals" else None,
        where_prefix=value if mode == "prefix" else None,
    )
    result["projection"] = projection
    return result


def _presentation(schema: Any) -> Any:
    """Remove only cosmetic schema titles, never property names or literal payloads."""
    if not isinstance(schema, dict):
        return deepcopy(schema)
    result = {}
    for key, value in schema.items():
        if key == "title" and isinstance(value, str):
            continue
        if key in {"properties", "$defs", "patternProperties", "dependentSchemas"}:
            value = {name: _presentation(child) for name, child in value.items()}
        elif key in {"anyOf", "oneOf", "allOf", "prefixItems"}:
            value = [_presentation(child) for child in value]
        elif key in {
            "items",
            "additionalProperties",
            "not",
            "if",
            "then",
            "else",
            "contains",
            "propertyNames",
            "unevaluatedProperties",
        }:
            value = _presentation(value)
        result[key] = deepcopy(value)
    return result


def _wire(schema: dict[str, Any], definitions: dict[str, Any]) -> dict[str, Any]:
    from hub.agent_native import _parameters

    selected = _parameters(schema, definitions)
    refs = selected.pop("$defs", None)
    result = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"arguments": selected},
        "required": ["arguments"],
        **({"$defs": refs} if refs else {}),
    }
    result = _presentation(result)
    assert isinstance(result, dict)
    Draft202012Validator.check_schema(result)
    return result


def add_facades(
    data: dict[str, Any], tools: list[dict[str, Any]], bindings: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return covered original HTTP definitions for private validation/history only."""
    from hub.agent_native import _canonical_parameters

    offered: list[dict[str, Any]] = []
    originals = []
    for origin_name, origin in list(bindings.items()):
        if (
            origin.get("kind") != "tool"
            or origin.get("tool") != "http"
            or "canonical_function" in origin
        ):
            continue
        definition = next(t["function"] for t in tools if t["function"]["name"] == origin_name)
        canonical = _canonical_parameters(definition, origin)
        branches = canonical.get("anyOf", [canonical])
        if not branches or any(
            set(branch)
            - {
                "title",
                "type",
                "properties",
                "required",
                "additionalProperties",
                "$defs",
            }
            for branch in branches
        ):
            continue  # Never drop unknown object-level constraints from an active view.
        variants = []
        methods = []
        for branch in branches:
            properties = branch.get("properties", {})
            method = properties.get("method", {})
            choices = method.get("enum", [method.get("const")])
            if not choices or any(
                m not in {"GET", "POST", "PUT", "PATCH", "DELETE"} for m in choices
            ):
                break
            methods.extend(choices)
            read = choices == ["GET"]
            names = (
                ("path", "query")
                if read
                else (
                    "method",
                    "path",
                    "query",
                    "body",
                    "verification",
                )
            )
            selected = {key: deepcopy(properties[key]) for key in names if key in properties}
            interface: dict[str, Any] = next(
                (
                    row
                    for row in data["interfaces"]
                    if row["integration_id"] == origin["integration_id"]
                ),
                {},
            )
            if read and interface.get("kind") == "home_assistant":
                from hub.agent_path_grammar import ha_read_path_pattern

                pattern = ha_read_path_pattern(interface.get("rules", {}).get("http_prefixes", []))
                if pattern is not None:
                    selected["path"]["pattern"] = pattern
                else:
                    continue
            variants.append(
                (
                    "read" if read else "change",
                    selected,
                    [key for key in branch.get("required", []) if key in selected],
                )
            )
        else:
            # GET webhooks are effects at HA. A read-only facade never offers them,
            # but the original authorized capability remains available as a change.
            if "GET" in methods:
                for kind, props, _required in variants:
                    if kind == "change":
                        props["method"]["enum"] = list(
                            dict.fromkeys(
                                [
                                    *props["method"].get("enum", []),
                                    "GET",
                                ]
                            )
                        )
                if (
                    not any(kind == "change" for kind, _, _ in variants)
                    and interface.get("kind") == "home_assistant"
                    and interface.get("read_only") is not True
                    and original_read_only(data) is False
                ):
                    props = branches[0]["properties"]
                    variants.append(
                        (
                            "change",
                            {
                                key: deepcopy(props[key])
                                for key in (
                                    "method",
                                    "path",
                                    "query",
                                    "body",
                                    "verification",
                                )
                                if key in props
                            },
                            ["method", "path"],
                        )
                    )
            # Advanced projection is deliberately flat: no nullable Projection object,
            # and a filter pointer/operator/value must always be explicit.
            union = branches[-1]["properties"]
            selected = {
                key: deepcopy(union[key])
                for key in (
                    "path",
                    "query",
                    "body",
                    "verification",
                )
                if key in union
            }
            selected["method"] = {"type": "string", "enum": list(dict.fromkeys(methods))}
            paths = [branch["properties"]["path"] for branch in branches]
            if any(path != paths[0] for path in paths):
                selected["path"] = {"anyOf": deepcopy(paths)}
            projection = canonical.get("$defs", {}).get("Projection", {})
            if not projection:
                continue
            for key in ("items_path", "fields", "limit"):
                selected[key] = deepcopy(projection["properties"][key])
            selected.update(
                filter_mode={"type": "string", "enum": ["none", "equals", "prefix"]},
                filter_field={"type": "string", "maxLength": 1000},
                filter_value={},
            )
            variants.append(
                (
                    "project",
                    selected,
                    ["method", "path", "filter_mode", "filter_field", "filter_value"],
                )
            )
            for kind, properties, required in variants:
                name = origin_name + "_" + kind
                if name in bindings:
                    raise ValueError("HTTP facade collision")
                parameters = _wire(
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": properties,
                        "required": required,
                        **(
                            {
                                "allOf": [
                                    {
                                        "if": {"properties": {"filter_mode": {"const": "none"}}},
                                        "then": {
                                            "properties": {
                                                "filter_field": {"const": ""},
                                                "filter_value": {"type": "null"},
                                            }
                                        },
                                        "else": {"properties": {"filter_field": {"minLength": 1}}},
                                    },
                                    {
                                        "if": {"properties": {"filter_mode": {"const": "prefix"}}},
                                        "then": {
                                            "properties": {"filter_value": {"type": "string"}}
                                        },
                                    },
                                ]
                            }
                            if kind == "project"
                            else {}
                        ),
                    },
                    canonical.get("$defs", {}),
                )
                descriptions = {
                    "read": "GET permitted relative path. No body/verification.",
                    "change": "Authorized change: exact method/path/body and independent "
                    "verification. Permissions unchanged.",
                    "project": "Flat response selection: none uses field='' and value=null; "
                    "equals keeps JSON type; prefix needs string. filter_field: explicit pointer. "
                    "items_path: list; fields/limit: bounded output. Canonical rules unchanged.",
                }
                offered.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": f"integration_id={origin['integration_id']}. "
                            + descriptions[kind],
                            "parameters": parameters,
                        },
                    }
                )
                bindings[name] = {**origin, "canonical_function": origin_name, "http_facade": kind}
            originals.append({"type": "function", "function": deepcopy(definition)})
    if data.get("execution_state", {}).get("phase") == "act":
        offered.sort(key=lambda item: not item["function"]["name"].endswith("_change"))
    tools[:0] = offered
    return originals


def normalized_http(arguments: dict[str, Any]) -> str:
    from hub.action_api import encode

    return encode(HTTPCall.model_validate(arguments).model_dump(mode="json"))


def history_alias(
    metadata: dict[str, Any], identifier: str, arguments: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    """Prefer a simple model-visible history name only after an exact semantic roundtrip."""
    for name, binding in metadata["bindings"].items():
        if (
            binding.get("integration_id") != identifier
            or "http_facade" not in binding
            or not any(t["function"]["name"] == name for t in metadata["tools"])
        ):
            continue
        kind = binding["http_facade"]
        candidate: dict[str, Any]
        if kind == "read":
            candidate = {
                key: deepcopy(arguments[key]) for key in ("path", "query") if key in arguments
            }
        elif kind == "change":
            candidate = deepcopy(arguments)
            if candidate.get("projection") is None:
                candidate.pop("projection", None)
        else:
            projection = arguments.get("projection")
            if not isinstance(projection, dict):
                continue
            candidate = {k: deepcopy(v) for k, v in arguments.items() if k != "projection"}
            candidate.update(
                {
                    k: deepcopy(projection[k])
                    for k in ("items_path", "fields", "limit")
                    if k in projection
                }
            )
            pointer, prefix = projection.get("where_pointer"), projection.get("where_prefix")
            mode = "none" if pointer is None else "prefix" if prefix is not None else "equals"
            candidate.update(
                filter_mode=mode,
                filter_field=pointer if pointer is not None else "",
                filter_value=deepcopy(
                    prefix
                    if mode == "prefix"
                    else projection.get("where_equals")
                    if mode == "equals"
                    else None
                ),
            )
        try:
            from hub.agent_native import _canonical_parameters

            definition = next(
                row["function"] for row in metadata["tools"] if row["function"]["name"] == name
            )
            if not Draft202012Validator(_canonical_parameters(definition, binding)).is_valid(
                candidate
            ):
                continue
            if normalized_http(canonical_arguments(binding, candidate)) == normalized_http(
                arguments
            ):
                return name, candidate
        except ValueError:
            continue
    return None


def original_read_only(data: dict[str, Any]) -> bool:
    return data.get("read_only") is True
