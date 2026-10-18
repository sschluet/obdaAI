"""Bounded model views; persisted originals and execution authority stay unchanged."""

import hashlib
import json
from typing import Any


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


def fit(data: dict[str, Any], instruction: str, context_limit: int) -> dict[str, Any]:
    """Reduce evidence views, never authority, targets, goal or tool contracts."""
    result = dict(data)
    original = data.get("history", [])
    for size in (6000, 3000, 1500, 600, 180):
        result["private_context"] = view(data.get("private_context", []), size)
        result["history"] = [
            {
                **entry,
                "document": view(entry["document"], size),
                "result": view(entry["result"], size if i == len(original) - 1 else size // 2),
            }
            for i, entry in enumerate(original)
        ]
        if len(instruction) + len(json.dumps(result, ensure_ascii=False)) <= context_limit - 200:
            return result
    raise ValueError("Goal, authority or evidence exceeds the model context limit")
