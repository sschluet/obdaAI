"""Frozen entity requirements narrow real reads, without replacing other predicates."""

import copy

import pytest
from hub.agent_read_projection import narrow_entity_read

INTENT = {"requirements": [{"kind": "entity_states", "domain": "sensor",
                            "integration_id": "target"}]}


def narrow(arguments, intent=INTENT):
    return narrow_entity_read("home_assistant", "target", "http", arguments, intent)


def test_actual_broad_model_projection_is_narrowed_and_keeps_original_immutable():
    args = {"method": "GET", "path": "/api/states", "projection": {
        "items_path": "", "where_pointer": None, "where_prefix": None, "where_equals": None,
        "fields": ["/attributes/friendly_name"], "limit": 7,
    }}
    original = copy.deepcopy(args)
    projected = narrow(args)["projection"]
    assert projected["where_pointer"] == "/entity_id"
    assert projected["where_prefix"] == "sensor."
    assert projected["fields"] == ["/attributes/friendly_name", "/entity_id", "/state"]
    assert projected["limit"] == 7 and args == original


@pytest.mark.parametrize(("pointer", "prefix", "expected"), [
    ("/entity_id", "s", "sensor."),
    ("/entity_id", "sensor.temperature", "sensor.temperature"),
    ("/entity_id", "light.", "light."),
    ("/state", "on", "on"),
])
def test_existing_narrower_or_different_filter_is_never_widened(pointer, prefix, expected):
    args = {"method": "GET", "path": "/api/states", "projection": {
        "where_pointer": pointer, "where_prefix": prefix, "fields": [], "limit": 3,
    }}
    result = narrow(args)["projection"]
    assert result["where_prefix"] == expected and result["fields"] == []


def test_multiple_domains_or_other_endpoint_do_not_gain_an_invented_filter():
    args = {"method": "GET", "path": "/api/states"}
    intent = {"requirements": [*INTENT["requirements"], {
        "kind": "entity_states", "domain": "light", "integration_id": "target",
    }]}
    assert narrow(args, intent) == args
    assert narrow({"method": "GET", "path": "/api/config"}) == {
        "method": "GET", "path": "/api/config",
    }
