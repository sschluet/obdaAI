"""GET-capable HA webhooks trigger automations and are never read evidence."""

import pytest
from hub.agent_tools import Rules, validate_tool


@pytest.fixture
def rules():
    return Rules(enabled=True, http_prefixes=["/"], http_methods=["GET", "POST"])


@pytest.mark.parametrize("path", ["/api/webhook/synthetic-id", "/api/webhook/synthetic-id/",
    "/API/WEBHOOK/synthetic-id", "/Api/WebHook/synthetic-id", "/api/webhook",
    "/api/webhook/"])
def test_ha_get_webhook_is_an_effect_even_with_get_only_rules(rules, path):
    rules.http_methods = ["GET"]
    arguments, effect = validate_tool("home_assistant", rules, "http", {
        "method": "GET", "path": path,
    })
    assert effect and arguments["path"] == path


@pytest.mark.parametrize("path", ["/api//webhook/synthetic", "//api/webhook/synthetic",
    "/api/webhook//synthetic", "/api/./webhook/synthetic", "/api/%77ebhook/synthetic"])
def test_noncanonical_webhook_variants_are_rejected_before_transport(rules, path):
    with pytest.raises(ValueError):
        validate_tool("home_assistant", rules, "http", {"method": "GET", "path": path})


@pytest.mark.parametrize("path", ["/api/webhook/synthetic", "/API/WEBHOOK/synthetic"])
def test_webhook_cannot_be_a_standalone_or_embedded_read_verification(rules, path):
    with pytest.raises(PermissionError):
        validate_tool("home_assistant", rules, "http.verify", {
            "path": path, "effect_step": 1, "expected": {"/http_status": 200},
        })
    with pytest.raises(PermissionError):
        validate_tool("home_assistant", rules, "http", {
            "method": "POST", "path": "/api/services/light/turn_on",
            "verification": {"path": path, "expected": {"/http_status": 200}},
        })


@pytest.mark.parametrize("path", ["/api/", "/api/states", "/api/config", "/api/services",
    "/api/webhook_status", "/api/webhooks/synthetic"])
def test_ordinary_ha_gets_keep_existing_read_semantics(rules, path):
    _, effect = validate_tool("home_assistant", rules, "http", {"path": path})
    assert effect is False


def test_other_adapters_do_not_inherit_ha_route_semantics(rules):
    _, effect = validate_tool("paperless", rules, "http", {"path": "/api/webhook/synthetic"})
    assert effect is False
