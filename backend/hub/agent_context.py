"""Bounded model views; persisted originals and execution authority stay unchanged."""

import hashlib
import json
from typing import Any


class AgentContextLimitError(ValueError):
    reason = "local_context_limit"


def pointer(value: Any, path: str) -> Any:
    if path == "":
        return value
    if not path.startswith("/"):
        raise ValueError("Expected a JSON pointer")
    for key in path[1:].split("/"):
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def project(body: Any, rule: dict[str, Any]) -> dict[str, Any]:
    selected = pointer(body, rule["items_path"])
    if not isinstance(selected, list):
        raise ValueError("Projection requires a list response")
    if rule["where_pointer"] is not None:

        def matches(item: Any) -> bool:
            try:
                field = pointer(item, rule["where_pointer"])
                if rule["where_prefix"] is not None:
                    return isinstance(field, str) and field.startswith(rule["where_prefix"])
                return type(field) is type(rule["where_equals"]) and field == rule["where_equals"]
            except (KeyError, TypeError, IndexError, ValueError):
                return False

        selected = [item for item in selected if matches(item)]
    matched = len(selected)
    selected = selected[: rule["limit"]]
    if rule["fields"]:
        projected = []
        for item in selected:
            row = {}
            for field in rule["fields"]:
                try:
                    row[field] = pointer(item, field)
                except (KeyError, TypeError, IndexError, ValueError):
                    row[field] = None
            projected.append(row)
        selected = projected
    return {"items": selected, "matched": matched, "returned": len(selected)}


def view(value: Any, limit: int) -> Any:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= limit:
        return value
    return {
        "excerpt": text[: max(0, limit - 160)],
        "truncated": True,
        "full_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _shape(value: Any, *, depth: int = 0, width: int = 12) -> dict[str, Any]:
    """Describe observed JSON structure, never infer fields from a tool contract."""
    if isinstance(value, dict):
        # Preserve conventional payload containers even behind large metadata fields.
        keys = list(value)
        priority = [key for key in ("results", "items", "data") if key in value]
        selected = (priority + [key for key in keys if key not in priority])[:width]
        result: dict[str, Any] = {
            "type": "object",
            "key_count": len(keys),
            "keys": [key[:48] for key in selected],
            "keys_omitted": len(keys) - len(selected),
            "key_names_truncated": any(len(key) > 48 for key in selected),
        }
        if depth < 1:
            # A list of pairs avoids collisions between truncated long field names.
            result["fields"] = [
                {
                    "key": key[:48],
                    "key_truncated": len(key) > 48,
                    "shape": _shape(value[key], depth=depth + 1, width=width),
                }
                for key in selected
            ]
        return result
    if isinstance(value, list):
        sampled = value[:3]
        item_keys: list[str] = []
        for item in sampled:
            if isinstance(item, dict):
                for key in item:
                    if key not in item_keys and len(item_keys) < width:
                        item_keys.append(key)
        return {
            "type": "array",
            "length": len(value),
            "sampled_items": len(sampled),
            "sample_item_types": list(dict.fromkeys(_json_type(item) for item in sampled)),
            "sample_item_keys": [key[:48] for key in item_keys],
            "sample_item_key_names_truncated": any(len(key) > 48 for key in item_keys),
        }
    result = {"type": _json_type(value)}
    if isinstance(value, str):
        result["length"] = len(value)
    return result


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    return "number"


def _observation(
    entry: dict[str, Any], *, result_limit: int = 1500, metadata_limit: int = 2500
) -> dict[str, Any]:
    observed = entry["result"]
    summary: dict[str, Any] = {}
    if isinstance(observed, dict):
        # Extract before clipping: sorted JSON can put a huge body before these fields.
        for key in (
            "http_status",
            "effect_verified",
            "verification_passed",
            "projection_error",
            "exit_code",
            "verification_method",
            "causation_verified",
            "smtp_accepted",
            "delivery_verified",
            "error",
        ):
            if key in observed:
                summary[key] = view(observed[key], 200)
        if isinstance(observed.get("verification"), dict):
            verification = observed["verification"]
            summary["verification"] = {
                key: view(verification[key], 200)
                for key in ("exit_code", "error")
                if key in verification
            }
    for width in (12, 6, 3, 1):
        summary["result_shape"] = _shape(observed, width=width)
        if isinstance(observed, dict) and "body" in observed:
            summary["body_shape"] = _shape(observed["body"], width=width)
        if len(json.dumps(summary, ensure_ascii=False)) <= metadata_limit:
            break
    else:
        raise AgentContextLimitError("Observation metadata exceeds the model context limit")
    encoded = json.dumps(observed, ensure_ascii=False, separators=(",", ":"))
    return {
        "sequence": entry.get("sequence"),
        "full_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "summary": summary,
        "result": view(observed, result_limit),
    }


def _projected_mail_observation(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Typed mail evidence already has a protected semantic view; do not duplicate it."""
    result = entry["result"]
    if not isinstance(result, dict):
        return None
    projection = result.get("model_projection")
    if result.get("catalog_checked") is True:
        projection = "mail_catalog"
    response = result.get("response")
    content = response.get("content") if isinstance(response, dict) else None
    if isinstance(content, list) and content and isinstance(content[0], dict):
        projection = content[0].get("model_projection", projection)
    if projection not in {"mail_catalog", "mail_query_receipt", "folder_catalog", "folder_status"}:
        return None
    return {
        "sequence": entry.get("sequence"),
        "full_sha256": hashlib.sha256(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest(),
        "model_projection": projection,
        "evidence_source": "mail_read_progress",
    }


def fit(
    data: dict[str, Any], instruction: str, context_limit: int, *, max_bytes: int | None = None
) -> dict[str, Any]:
    """Reduce evidence views, never authority, targets, goal or tool contracts.

    The latest tool observation keeps an independent structural/verification summary
    and a larger excerpt even when older history must shrink. All views are derived;
    persisted original evidence and its execution authority remain untouched.
    """
    result = dict(data)
    original = data.get("history", [])
    latest = next(
        (
            entry
            for entry in reversed(original)
            if entry.get("kind") in {"read", "effect", "verification", "research"}
            or isinstance(entry.get("document"), dict)
            and "tool" in entry["document"]
        ),
        None,
    )
    latest_input = next(
        (entry for entry in reversed(original) if entry.get("kind") == "input"), None
    )
    if latest_input is not None:
        result["latest_input"] = latest_input
    for size in (6000, 3000, 1500, 600, 180):
        if latest is not None:
            protected = (
                _projected_mail_observation(latest) if "mail_read_progress" in data else None
            )
            result["latest_observation"] = protected or _observation(
                latest,
                result_limit=min(size, 1500) if max_bytes is not None else 1500,
                metadata_limit=1000 if max_bytes is not None else 2500,
            )
        result["private_context"] = view(data.get("private_context", []), size)

        def history_result(entry: dict[str, Any], limit: int, budget: int = size) -> Any:
            projected = _projected_mail_observation(entry) if "mail_read_progress" in data else None
            if projected is not None and budget <= 600:
                return {
                    "evidence_source": "mail_read_progress",
                }
            return view(entry["result"], limit)

        def history_document(entry: dict[str, Any], budget: int = size) -> Any:
            projected = _projected_mail_observation(entry) if "mail_read_progress" in data else None
            document = entry["document"]
            if projected is not None and budget <= 600 and isinstance(document, dict):
                return {
                    key: document[key] for key in ("tool", "integration_id") if key in document
                } | (
                    {"arguments": {"name": document["arguments"]["name"]}}
                    if isinstance(document.get("arguments"), dict)
                    and "name" in document["arguments"]
                    else {}
                )
            return view(document, budget)

        result["history"] = [
            {
                **entry,
                "document": history_document(entry),
                "result": history_result(entry, size if i == len(original) - 1 else size // 2),
            }
            for i, entry in enumerate(original)
        ]
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        byte_length = len(instruction.encode()) + len(encoded.encode())
        if len(instruction) + len(
            json.dumps(result, ensure_ascii=False)
        ) <= context_limit - 200 and (max_bytes is None or byte_length <= max_bytes):
            return result
    raise AgentContextLimitError("Goal, authority or evidence exceeds the model context limit")
