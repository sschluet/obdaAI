import asyncio
import importlib.util
import json
import time
from pathlib import Path

import pytest
from hub.config import Settings
from hub.db import Base, SourceNetworkRequest, session_factory
from hub.source_network import grant, lease_targets, request_network, requests_plan
from sqlalchemy import select


@pytest.mark.parametrize(
    "kind,config,ip",
    [
        ("website", {"url": "https://example.org/"}, "127.0.0.1"),
        ("website", {"url": "https://example.org/"}, "192.168.1.10"),
        ("sql", {"server": "server", "port": 5432}, "169.254.169.254"),
        ("nfs", {"server": "server"}, "93.184.215.14"),
    ],
)
def test_leases_reject_system_private_http_and_public_nfs(monkeypatch, kind, config, ip):
    monkeypatch.setattr(
        "hub.source_network.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (ip, 443))]
    )
    assert lease_targets(kind, config) == []


def test_manual_public_and_private_protocols_are_exact_numeric_targets(monkeypatch):
    monkeypatch.setattr(
        "hub.source_network.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("192.168.1.10", 445))],
    )
    assert lease_targets("smb", {"server": "nas", "port": 1445}) == [("192.168.1.10", 1445)]
    assert lease_targets("nfs", {"server": "nas"}) == [
        ("192.168.1.10", 111),
        ("192.168.1.10", 2049),
    ]
    assert lease_targets("shell", {"server": "nas"}) == []
    assert lease_targets("website", {"url": "https://user:secret@example.org/"}) == []


def test_root_observer_uses_only_own_chain_numeric_args_and_preserves_existing_rules(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "source_observer", Path("deploy/source-network.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    class Result:
        returncode = 1

    def cmd(*args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr(module, "command", cmd)
    ids = module.apply(
        [
            {
                "id": "synthetic",
                "kind": "website",
                "targets": [
                    ["93.184.215.14", 443],
                    ["127.0.0.1", 443],
                    ["192.168.1.1", 443],
                    ["93.184.215.14", 22],
                ],
            }
        ]
    )
    assert ids == ["synthetic"]
    assert any("93.184.215.14" in c and "443" in c for c in calls)
    assert all(not ("-F" in c and "OBDAAI_APP" in c) for c in calls)
    assert all(not ("-d" in c and "127.0.0.1" in c) for c in calls)
    assert all("INPUT" not in c and "OUTPUT" not in c for c in calls)


def test_lease_waits_for_applied_ack_and_expired_requests_are_never_granted(tmp_path, monkeypatch):
    factory = session_factory("sqlite:///" + str(tmp_path / "leases.sqlite"))
    Base.metadata.create_all(factory.kw["bind"])
    monkeypatch.setattr(
        "hub.source_network.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.215.14", 443))],
    )
    with factory() as db:
        old = SourceNetworkRequest(
            kind="website", config=json.dumps({"url": "https://example.org/"}),
            expires=time.time() - 1,
        )
        db.add(old)
        db.commit()
        expired_id = old.id

    async def run():
        pending = asyncio.create_task(request_network(
            factory, Settings(source_network_enabled=True), "website",
            {"url": "https://example.org/"},
        ))
        await asyncio.sleep(0.05)
        assert not pending.done()
        plan = requests_plan(factory)
        assert len(plan) == 1 and plan[0]["id"] != expired_id
        assert plan[0]["targets"] == [("93.184.215.14", 443)]
        grant(factory, [plan[0]["id"], expired_id])
        await asyncio.wait_for(pending, 1)

    asyncio.run(run())
    with factory() as db:
        assert not db.get(SourceNetworkRequest, expired_id).granted
        assert sum(r.granted for r in db.scalars(select(SourceNetworkRequest))) == 1


def test_disabled_feature_creates_no_network_request(tmp_path):
    factory = session_factory("sqlite:///" + str(tmp_path / "disabled.sqlite"))
    Base.metadata.create_all(factory.kw["bind"])
    asyncio.run(request_network(factory, Settings(), "website", {"url": "https://example.org/"}))
    with factory() as db:
        assert list(db.scalars(select(SourceNetworkRequest))) == []
