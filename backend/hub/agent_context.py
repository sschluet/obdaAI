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


def _object_view(body: dict[str, Any], path: str, limit: int) -> dict[str, Any] | None:
    """Observed scalar facts only; omitted containers never become a complete body."""
    result: dict[str, Any] = {
        "object_path": path, "model_view_only": True, "fields": {},
        "observed_field_count": len(body), "omitted_field_count": len(body),
        "containers_omitted": sum(isinstance(value, (dict, list)) for value in body.values()),
    }
    priority = ("version", "state", "installation_type", "installationtype", "install_type",
                "installation_method", "safe_mode", "recovery_mode", "debug", "enabled")
    keys = [key for key in priority if key in body]
    keys.extend(sorted(key for key in body if key not in priority))
    for key in keys:
        value = body[key]
        if (len(key) > 80 or isinstance(value, (dict, list))
                or not (value is None or type(value) in {str, bool, int, float})):
            continue
        candidate = {**result, "fields": {**result["fields"], key: value},
                     "omitted_field_count": len(body) - len(result["fields"]) - 1}
        if len(json.dumps(candidate, ensure_ascii=False).encode()) <= limit:
            result = candidate
        if len(result["fields"]) >= 32:
            break
    return result if len(json.dumps(result, ensure_ascii=False).encode()) <= limit else None


def _semantic_view(observed: Any, limit: int) -> dict[str, Any] | None:
    """Loss-aware typed rows, rather than a JSON prefix ending mid-value.

    This is only a model view. Completion checks always inspect original receipts.
    """
    if not isinstance(observed, dict):
        return None
    payload_key = "body" if "body" in observed else "response" if "response" in observed else None
    body = observed[payload_key] if payload_key else observed
    path = "/" + payload_key if payload_key else ""
    if isinstance(body, dict):
        key = next((key for key in ("results", "items", "data")
                    if isinstance(body.get(key), list)), None)
        if key is None:
            return _object_view(body, path, limit)
        items, path = body[key], path + "/" + key
    elif isinstance(body, list):
        items = body
    else:
        return None
    if not all(isinstance(item, dict) for item in items):
        return None
    counts: dict[str, int] = {}
    for item in items:
        entity = item.get("entity_id", item.get("/entity_id"))
        if isinstance(entity, str) and "." in entity:
            domain = entity.split(".", 1)[0]
            if domain in counts or len(counts) < 32:
                counts[domain] = counts.get(domain, 0) + 1
    result: dict[str, Any] = {"items_path": path, "observed_count": len(items),
                              "items": [], "returned": 0, "truncated": bool(items)}
    if counts:
        result["observed_domain_counts"] = counts
    if isinstance(body, dict):
        source_counts = {key: body[key] for key in ("matched", "returned", "count", "total")
                         if type(body.get(key)) is int and body[key] >= 0}
        if source_counts:
            result["source_counts"] = source_counts
        if "next" in body or "nextPageToken" in body:
            result["source_has_more"] = bool(body.get("next") or body.get("nextPageToken"))
    for item in items[:32]:
        row = {key: view(item[key], 160) for key in (
            "entity_id", "state", "id", "name", "title", "created", "modified",
            "correspondent", "tags", "last_changed", "last_updated", "/entity_id", "/state",
            "/attributes/friendly_name", "/attributes/installed_version",
            "/attributes/latest_version", "/attributes/in_progress",
            "/attributes/supported_features") if key in item}
        if isinstance(item.get("attributes"), dict):
            row["attributes"] = {key: view(item["attributes"][key], 120) for key in (
                "friendly_name", "unit_of_measurement", "device_class", "installed_version",
                "latest_version", "in_progress", "supported_features")
                if key in item["attributes"]}
        if not row:
            row = {str(key): view(value, 80) for key, value in list(item.items())[:5]
                   if not isinstance(value, (dict, list))}
        candidate = {**result, "items": [*result["items"], row]}
        if len(json.dumps(candidate, ensure_ascii=False).encode()) > limit:
            break
        result["items"].append(row)
    result["returned"] = len(result["items"])
    result["truncated"] = len(items) != result["returned"]
    return result if len(json.dumps(result, ensure_ascii=False).encode()) <= limit else None


def _http_object_result(entry: dict[str, Any], limit: int) -> dict[str, Any] | None:
    """Keep literal facts for large GET objects, including failed selection views.

    Transport status and proof fields stay exact. Omissions describe the local
    model view, never partial execution of the remote command.
    """
    observed, document = entry.get("result"), entry.get("document")
    if (
        entry.get("kind") != "read"
        or entry.get("status") not in {"succeeded", "failed"}
        or not isinstance(observed, dict)
        or not isinstance(document, dict)
        or document.get("tool") != "http"
        or not isinstance(document.get("arguments"), dict)
        or document["arguments"].get("method") != "GET"
        or type(observed.get("http_status")) is not int
        or not 200 <= observed["http_status"] < 300
        or (entry.get("status") == "failed" and not observed.get("projection_error"))
        or observed.get("effect_verified") is True
        or not isinstance(observed.get("body"), dict)
        or any(isinstance(observed["body"].get(key), list) for key in ("results", "items", "data"))
        or len(json.dumps(observed, ensure_ascii=False, separators=(",", ":"))) <= limit
    ):
        return None
    body_view = _object_view(observed["body"], "/body", max(400, min(800, limit)))
    if body_view is None:
        return None
    return {
        **observed,
        "body": body_view["fields"],
        "body_view": {
            **{key: value for key, value in body_view.items() if key != "fields"},
            "full_sha256": _receipt_hash(observed["body"]),
        },
        "model_view_only": True,
        "full_sha256": _receipt_hash(observed),
    }


def _websocket_result(entry: dict[str, Any], limit: int) -> dict[str, Any] | None:
    """Typed bounded HA read data; no fabricated acknowledgement or verification."""
    observed, document = entry.get("result"), entry.get("document")
    if (
        entry.get("kind") != "read"
        or entry.get("status") != "succeeded"
        or not isinstance(observed, dict)
        or not isinstance(document, dict)
        or document.get("tool") != "ha.websocket"
        or "response" not in observed
        or observed.get("success") is False
        or observed.get("error")
        or observed.get("effect_verified") is True
        or len(json.dumps(observed, ensure_ascii=False, separators=(",", ":"))) <= limit
    ):
        return None
    payload = observed["response"]
    if isinstance(payload, dict) and not any(
        isinstance(payload.get(key), list) for key in ("results", "items", "data")
    ):
        typed = _object_view(payload, "/response", max(400, min(800, limit)))
        if typed is None:
            return None
        values = typed.pop("fields")
    elif isinstance(payload, list):
        typed = _semantic_view({"response": payload}, max(400, min(800, limit)))
        if typed is None:
            return None
        values = typed.pop("items")
        typed["row_fields_may_be_omitted"] = True
    else:
        return None
    return {
        **observed,
        "response": values,
        "response_view": {**typed, "model_view_only": True, "full_sha256": _receipt_hash(payload)},
        "model_view_only": True,
        "full_sha256": _receipt_hash(observed),
    }


def _typed_result(entry: dict[str, Any], limit: int) -> dict[str, Any] | None:
    return _http_object_result(entry, limit) or _websocket_result(entry, limit)


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
            "success",
            "failure_category",
            "failure_phase",
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
    semantic = _semantic_view(observed, min(800, metadata_limit // 2))
    if semantic is not None:
        summary["semantic_view"] = semantic
    for width in (12, 6, 3, 1):
        summary["result_shape"] = _shape(observed, width=width)
        if isinstance(observed, dict) and "body" in observed:
            summary["body_shape"] = _shape(observed["body"], width=width)
        if len(json.dumps(summary, ensure_ascii=False)) <= metadata_limit:
            break
    else:
        if "semantic_view" in summary:
            summary.pop("semantic_view")
        if len(json.dumps(summary, ensure_ascii=False)) > metadata_limit:
            raise AgentContextLimitError("Observation metadata exceeds the model context limit")
    encoded = json.dumps(observed, ensure_ascii=False, separators=(",", ":"))
    return {
        "sequence": entry.get("sequence"),
        "step_status": entry.get("status"),
        "model_view_only": True,
        "full_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "summary": summary,
        "result": _typed_result(entry, result_limit) or view(observed, result_limit),
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
    if projection in {"paperless_query_receipt", "mail_read_metadata"}:
        return {"sequence": entry.get("sequence"), "result": result}
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


def _read_index(
    entries: list[dict[str, Any]], latest: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deduplicate older successful read wrappers, preserving complete receipt hashes.

    Mutation, verification, failure, reconciliation and human-input records are
    never candidates. This derived index supplies provenance, not missing data.
    """
    groups: dict[str, dict[str, Any]] = {}
    retained = []
    protected = {"effect_verified", "verification", "verification_passed", "acknowledged",
                 "reconciled_after_uncertain", "causation_verified", "effect_step"}
    for entry in entries:
        document, result = entry.get("document"), entry.get("result")
        if (entry is latest or entry.get("kind") != "read" or entry.get("status") != "succeeded"
                or not isinstance(document, dict) or not isinstance(result, dict)
                or not isinstance(document.get("arguments", {}), dict)
                or _projected_mail_observation(entry) is not None
                or document.get("tool") in {"http.verify", "research"}
                or protected & (set(document) | set(result))
                or protected & set(document.get("arguments") or {})):
            retained.append(entry)
            continue
        arguments = document.get("arguments", {})
        operation = {"integration_id": document.get("integration_id"),
                     "tool": document.get("tool"),
                     "arguments_sha256": hashlib.sha256(json.dumps(
                         arguments, ensure_ascii=False, sort_keys=True,
                     ).encode()).hexdigest()}
        if isinstance(arguments, dict):
            operation.update({key: arguments[key] for key in ("method", "path", "name")
                              if key in arguments})
        key = json.dumps(operation, sort_keys=True)
        group = groups.setdefault(key, {**operation, "status": "succeeded", "receipts": [],
                                         "content_omitted": True, "model_view_only": True})
        group["receipts"].append({
            "sequence": entry.get("sequence"),
            "document_sha256": hashlib.sha256(json.dumps(
                document, ensure_ascii=False, separators=(",", ":"),
            ).encode()).hexdigest(),
            "result_sha256": hashlib.sha256(json.dumps(
                result, ensure_ascii=False, separators=(",", ":"),
            ).encode()).hexdigest(),
        })
    return retained, list(groups.values())


def _receipt_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def _effect_payload(value: Any, *, include_hash: bool = True) -> Any:
    """Only payload bytes may shrink; proof/control fields remain exact recursively."""
    if not isinstance(value, dict):
        return value
    result = {
        key: ({"content_omitted": True, "full_sha256": _receipt_hash(item)}
              if len(json.dumps(item, ensure_ascii=False)) > 180 else item) if key in {
            "body", "stdout", "stderr", "script", "command", "verification_script", "content",
        } else _effect_payload(item, include_hash=False)
        for key, item in value.items()
    }

    if include_hash and result != value and "full_sha256" not in value:
        result["full_sha256"] = _receipt_hash(value)
    return result


def _verified_terminal(entry: dict[str, Any]) -> bool:
    result = entry.get("result")
    return (entry.get("status") == "succeeded" and isinstance(result, dict)
            and (result.get("effect_verified") is True
                 or entry.get("kind") == "verification"
                 and result.get("verification_passed") is True))


def _effect_index(
    entries: list[dict[str, Any]], latest: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Index only explicitly verified terminal effects, never unresolved writes.

    Every sequence has its own hashes and exact proof vocabulary. This model view
    cannot authorize replay or substitute for original persisted receipts.
    """
    retained, ledger = [], []
    for entry in entries:
        document, result = entry.get("document"), entry.get("result")
        if (entry is latest or entry.get("kind") not in {"effect", "verification"}
                or entry.get("status") != "succeeded" or not isinstance(document, dict)
                or not isinstance(result, dict) or not _verified_terminal(entry)):
            retained.append(entry)
            continue
        ledger.append({
            **{key: value for key, value in entry.items() if key not in {"document", "result"}},
            "document": _effect_payload(document, include_hash=False),
            "result": _effect_payload(result, include_hash=False),
            "document_sha256": _receipt_hash(document),
            "arguments_sha256": _receipt_hash(document.get("arguments", {})),
            "result_sha256": _receipt_hash(result),
            "model_view_only": True,
        })
    return retained, ledger


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
                _projected_mail_observation(latest)
                if "mail_read_progress" in data or "private_read_evidence" in data else None
            )
            result["latest_observation"] = protected or _observation(
                latest,
                result_limit=min(size, 1500) if max_bytes is not None else 1500,
                metadata_limit=1000 if max_bytes is not None else 2500,
            )
        result["private_context"] = view(data.get("private_context", []), size)

        def history_result(entry: dict[str, Any], limit: int, budget: int = size) -> Any:
            projected = (
                _projected_mail_observation(entry)
                if "mail_read_progress" in data or "private_read_evidence" in data else None
            )
            if projected is not None and budget <= 600:
                return {
                    "evidence_source": "mail_read_progress",
                }
            typed_object = _typed_result(entry, limit)
            if typed_object is not None:
                return typed_object
            observed = entry["result"]
            clipped = view(observed, limit)
            if (isinstance(observed, dict) and isinstance(clipped, dict)
                    and clipped.get("truncated") is True
                    and (entry.get("kind") in {"effect", "verification"}
                         or any(key in observed for key in (
                             "effect_verified", "verification_passed", "reconciled_after_uncertain"
                         )))):
                # Keep the original top-level proof vocabulary, even when body
                # precedes it in JSON. These are model views, never new receipts.
                clipped = {**clipped, **{key: observed[key] for key in (
                    "effect_verified", "verification_passed", "acknowledged",
                    "reconciled_after_uncertain", "causation_verified", "smtp_accepted",
                    "delivery_verified", "verification_method", "exit_code", "http_status",
                    "failure_category", "failure_phase",
                ) if key in observed}}
                if isinstance(observed.get("verification"), dict):
                    clipped["verification"] = {
                        key: view(observed["verification"][key], 200)
                        for key in ("exit_code", "error", "verification_passed", "effect_verified")
                        if key in observed["verification"]
                    }
            return clipped

        def history_document(entry: dict[str, Any], budget: int = size) -> Any:
            projected = (
                _projected_mail_observation(entry)
                if "mail_read_progress" in data or "private_read_evidence" in data else None
            )
            document = entry["document"]
            if (entry.get("kind") in {"effect", "verification"} and isinstance(document, dict)
                    and len(json.dumps(document, ensure_ascii=False)) > budget):
                arguments = document.get("arguments", {})
                protected_document = {
                    key: document[key] for key in ("tool", "integration_id", "target")
                    if key in document
                }
                protected_document["full_sha256"] = hashlib.sha256(json.dumps(
                    document, ensure_ascii=False, separators=(",", ":"),
                ).encode()).hexdigest()
                protected_document["arguments_sha256"] = hashlib.sha256(json.dumps(
                    arguments, ensure_ascii=False, separators=(",", ":"),
                ).encode()).hexdigest()
                if isinstance(arguments, dict):
                    protected_document["arguments"] = {
                        key: arguments[key] for key in ("verification", "effect_step")
                        if key in arguments
                    }
                protected_document["content_omitted"] = True
                return protected_document
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

        retained, index = (_read_index(original, latest) if size <= 600 else (original, []))
        retained, ledger = (_effect_index(retained, latest) if size <= 600 else (retained, []))
        if ledger:
            result["effect_ledger"] = ledger
        else:
            result.pop("effect_ledger", None)
        if index:
            result["older_read_index"] = index
        else:
            result.pop("older_read_index", None)
        result["history"] = [
            {
                **entry,
                "document": (
                    _effect_payload(entry["document"])
                    if entry.get("kind") in {"effect", "verification"}
                    and not _verified_terminal(entry) else history_document(entry)
                ),
                "result": (
                    _effect_payload(entry["result"])
                    if entry.get("kind") in {"effect", "verification"}
                    and not _verified_terminal(entry) else history_result(
                        entry, size if i == len(retained) - 1 else size // 2,
                    )
                ),
            }
            for i, entry in enumerate(retained)
        ]
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        byte_length = len(instruction.encode()) + len(encoded.encode())
        # Match action_api.encode at dispatch: whitespace that is never sent must
        # not consume the model budget. UTF-8 capacity remains a separate bound.
        if (len(instruction) + len(encoded) <= context_limit - 200
                and (max_bytes is None or byte_length <= max_bytes)):
            return result
    raise AgentContextLimitError("Goal, authority or evidence exceeds the model context limit")
