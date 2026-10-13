"""Explicit server allowlist is JSON configuration; default adds no new egress."""

import pytest
from hub.config import Settings


def test_native_server_allowlist_is_explicit_json(monkeypatch):
    monkeypatch.delenv("HUB_EXTERNAL_PROVIDER_KINDS", raising=False)
    assert Settings.from_env().external_provider_kinds == ("openrouter",)
    monkeypatch.setenv("HUB_EXTERNAL_PROVIDER_KINDS", '["openrouter","openai","anthropic"]')
    assert Settings.from_env().external_provider_kinds == ("openrouter", "openai", "anthropic")


def test_native_server_allowlist_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("HUB_EXTERNAL_PROVIDER_KINDS", '["arbitrary-cloud"]')
    with pytest.raises(ValueError):
        Settings.from_env()
