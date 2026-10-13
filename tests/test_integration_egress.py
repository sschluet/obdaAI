"""The observer touches only its own chain and never grants blanket outbound access."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_profile_rules_numeric_targets_only_and_own_chain(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "integration_egress", Path(__file__).parents[1] / "deploy" / "integration-network.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    commands = []

    def command(*args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=1 if "-C" in args else 0)

    monkeypatch.setattr(module, "command", command)
    ids = module.apply(
        [
            {"id": "allowed", "kind": "paperless", "targets": [("192.168.20.10", 8443)]},
            {"id": "blocked", "kind": "mcp", "targets": [("169.254.169.254", 80)]},
            {"id": "mapped", "kind": "mcp", "targets": [("::ffff:127.0.0.1", 80)]},
            {"id": "other", "kind": "website", "targets": [("1.1.1.1", 443)]},
        ]
    )
    assert ids == ["allowed"]
    grants = [args for args in commands if args[-1] == "ACCEPT"]
    assert grants == [
        (
            "iptables",
            "-A",
            "OBDAAI_INTEGRATIONS",
            "-d",
            "192.168.20.10",
            "-p",
            "tcp",
            "--dport",
            "8443",
            "-j",
            "ACCEPT",
        )
    ]
    assert all(args[2] == "OBDAAI_INTEGRATIONS" for args in commands if args[1] == "-F")
    commands.clear()
    module.clear()
    assert all("OBDAAI_INTEGRATIONS" in args for args in commands)
    assert not any("ACCEPT" in args for args in commands)
