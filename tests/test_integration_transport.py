"""Configured LAN targets work while protected addresses and DNS rebinding stay blocked."""

import json

import pytest
from hub.config import Settings
from hub.db import Base, session_factory
from hub.integration_transport import canonical_url, pinned_target, requests_plan, resolved_targets
from hub.integrations import Integration


def answers(monkeypatch, values):
    monkeypatch.setattr(
        "hub.integration_transport.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", (value, 443)) for value in values],
    )


def test_pin_lan_https_preserves_tls_hostname_and_custom_port(monkeypatch):
    answers(monkeypatch, ["192.168.20.10"])
    assert pinned_target(
        Settings(integration_targets_enabled=True), "https://PAPER.test:8443/app/"
    ) == (
        "https://192.168.20.10:8443/app/",
        {"Host": "paper.test:8443"},
        {"sni_hostname": "paper.test"},
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "100.100.100.200",
        "fd00:ec2::254",
    ],
)
def test_any_protected_dns_answer_blocks_before_credentials(monkeypatch, address):
    answers(monkeypatch, ["192.168.20.10", address])
    with pytest.raises(ValueError):
        pinned_target(Settings(integration_targets_enabled=True), "https://paper.test")


def test_http_only_on_validated_private_lan_and_flag_is_explicit(monkeypatch):
    answers(monkeypatch, ["192.168.20.10"])
    cfg = Settings(integration_targets_enabled=True)
    assert resolved_targets(cfg, "http://paper.test:8000") == [("192.168.20.10", 8000)]
    with pytest.raises(ValueError):
        pinned_target(Settings(), "https://paper.test")
    answers(monkeypatch, ["1.1.1.1"])
    with pytest.raises(ValueError):
        pinned_target(cfg, "http://paper.test")
    assert resolved_targets(cfg, "https://paper.test") == [("1.1.1.1", 443)]


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@paper.test",
        "https://paper.test?token=x",
        "https://paper.test/#fragment",
        "https://paper.test/../admin",
        "https://paper.test/%2e%2e",
        "file:///secret",
    ],
)
def test_no_credential_or_path_smuggling(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_enabled_profiles_only_numeric_egress_no_secrets(monkeypatch):
    answers(monkeypatch, ["192.168.20.10"])
    factory = session_factory("sqlite://")
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as db:
        db.add_all(
            [
                Integration(
                    name="Enabled",
                    kind="paperless",
                    enabled=True,
                    config=json.dumps({"url": "https://paper.test"}),
                ),
                Integration(
                    name="Disabled",
                    kind="paperless",
                    enabled=False,
                    config=json.dumps({"url": "https://disabled.test"}),
                ),
                Integration(
                    name="Unsafe",
                    kind="paperless",
                    enabled=True,
                    config=json.dumps({"url": "https://127.0.0.1"}),
                ),
            ]
        )
        db.commit()
    plan = requests_plan(factory, Settings(integration_targets_enabled=True))
    assert len(plan) == 1 and plan[0]["targets"] == [("192.168.20.10", 443)]
    assert set(plan[0]) == {"id", "kind", "targets"}
    assert requests_plan(factory, Settings()) == []


def test_dynamic_mcp_catalog_preserves_trailing_endpoint_slash(monkeypatch):
    import httpx
    from hub.mcp_client import discover

    answers(monkeypatch, ["192.168.20.10"])
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.path == "/mcp/"
        assert request.headers["host"] == "mcp.test"
        message = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {"resultType": "complete", "tools": []},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = discover(
            client,
            Settings(integration_targets_enabled=True),
            "https://mcp.test/mcp/",
            "2026-07-28",
            "synthetic-token",
            configured_profile=True,
        )
    assert len(requests) == 1 and result["tools"] == []
