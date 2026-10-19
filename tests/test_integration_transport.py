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


def proton_pending_case():
    import time
    from uuid import uuid4

    factory = session_factory("sqlite://")
    Base.metadata.create_all(factory.kw["bind"])
    profile_id = str(uuid4())
    cfg = Settings(
        integration_targets_enabled=True,
        proton_bridge_integration_id=profile_id,
        proton_bridge_mcp_url="http://proton.example.test:18764/mcp",
    )
    with factory() as db:
        row = Integration(
            id=profile_id,
            name="Synthetic Proton",
            kind="mcp",
            revision=3,
            enabled=False,
            writes_enabled=False,
            config=json.dumps({"url": cfg.proton_bridge_mcp_url}),
            last_check=json.dumps(
                {
                    "revision": 3,
                    "status": "pending",
                    "proton_setup": {
                        "created": time.time(),
                        "request_id": str(uuid4()),
                        "fingerprint": "a" * 64,
                    },
                }
            ),
        )
        db.add(row)
        db.commit()
    return factory, cfg, profile_id


def test_only_pinned_disabled_proton_pending_catalog_gets_bounded_egress(monkeypatch):
    from dataclasses import replace

    answers(monkeypatch, ["192.168.20.10"])
    factory, cfg, profile_id = proton_pending_case()
    with factory() as db:
        pending = db.get(Integration, profile_id)
        db.add(
            Integration(
                name="Other disabled MCP",
                kind="mcp",
                enabled=False,
                writes_enabled=False,
                revision=3,
                config=pending.config,
                last_check=pending.last_check,
            )
        )
        db.commit()
    assert requests_plan(factory, cfg) == [
        {"id": profile_id, "kind": "mcp", "targets": [("192.168.20.10", 18764)]}
    ]
    assert requests_plan(factory, replace(cfg, integration_targets_enabled=False)) == []
    assert requests_plan(factory, replace(cfg, proton_bridge_integration_id="")) == []
    assert (
        requests_plan(
            factory, replace(cfg, proton_bridge_mcp_url="http://other.example.test:18764/mcp")
        )
        == []
    )
    with factory() as db:
        pending = db.get(Integration, profile_id)
        assert not pending.enabled and not pending.writes_enabled


@pytest.mark.parametrize(
    "change",
    [
        "expired",
        "future",
        "nan",
        "bool_time",
        "no_time",
        "bad_request",
        "bad_fingerprint",
        "stale_revision",
        "not_pending",
        "different_kind",
        "different_url",
        "write_enabled",
        "legacy_marker",
    ],
)
def test_pending_proton_egress_rejects_expired_unbound_or_malformed_state(monkeypatch, change):
    import time

    answers(monkeypatch, ["192.168.20.10"])
    factory, cfg, profile_id = proton_pending_case()
    with factory() as db:
        row = db.get(Integration, profile_id)
        checked = json.loads(row.last_check)
        marker = checked["proton_setup"]
        if change == "expired":
            marker["created"] = time.time() - 121
        elif change == "future":
            marker["created"] = time.time() + 10
        elif change == "nan":
            marker["created"] = float("nan")
        elif change == "bool_time":
            marker["created"] = True
        elif change == "no_time":
            marker.pop("created")
        elif change == "bad_request":
            marker["request_id"] = "not-a-request-identity"
        elif change == "bad_fingerprint":
            marker["fingerprint"] = "not-a-fingerprint"
        elif change == "stale_revision":
            checked["revision"] = row.revision - 1
        elif change == "not_pending":
            checked["status"] = "succeeded"
        elif change == "different_kind":
            row.kind = "paperless"
        elif change == "different_url":
            row.config = json.dumps({"url": "http://other.example.test:18764/mcp"})
        elif change == "write_enabled":
            row.writes_enabled = True
        elif change == "legacy_marker":
            checked["proton_setup"] = {"request_id": marker["request_id"], "fingerprint": "a" * 64}
        row.last_check = json.dumps(checked)
        db.commit()
    assert requests_plan(factory, cfg) == []
