"""Narrow an existing entity read to the frozen task's one domain, without dispatch."""

import copy
from collections.abc import Mapping
from typing import Any


def narrow_entity_read(
    kind: str, identifier: str, tool: str, arguments: dict[str, Any],
    intent: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = copy.deepcopy(arguments)
    if (kind != "home_assistant" or tool != "http" or result.get("method") != "GET"
            or result.get("path") != "/api/states" or not intent):
        return result
    domains = {item["domain"] for item in intent.get("requirements", [])
               if item.get("kind") == "entity_states" and item.get("integration_id") == identifier}
    if len(domains) != 1:
        return result
    domain = next(iter(domains)) + "."
    projection = result.get("projection")
    if projection is None:
        projection = {"items_path": "", "where_pointer": None, "where_equals": None,
                      "where_prefix": None, "fields": [], "limit": 100}
    if projection.get("items_path", "") != "":
        return result
    pointer, prefix = projection.get("where_pointer"), projection.get("where_prefix")
    if pointer is None or pointer == "/entity_id" and prefix is None \
            and projection.get("where_equals") is None:
        projection["where_pointer"], projection["where_prefix"] = "/entity_id", domain
        projection["where_equals"] = None
    elif pointer == "/entity_id" and isinstance(prefix, str):
        if domain.startswith(prefix):
            projection["where_prefix"] = domain
        elif not prefix.startswith(domain):
            return result  # Conflicting predicate must not be replaced with a broader one.
    elif not (pointer == "/entity_id" and isinstance(projection.get("where_equals"), str)
              and projection["where_equals"].startswith(domain)):
        return result  # Preserve unrelated/narrower filters instead of widening their result set.
    fields = projection.get("fields", [])
    if fields:
        projection["fields"] = list(dict.fromkeys([*fields, "/entity_id", "/state"]))
    result["projection"] = projection
    return result
