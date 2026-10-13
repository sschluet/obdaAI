import json
import ssl
import uuid
from contextlib import nullcontext

import pytest
from fastapi import HTTPException
from hub.config import Settings
from hub.ha_backups import COMMANDS, exchange, inspect, summarize
from test_actions import gateway  # noqa: F401


def data():
    return [
        {"operating_system": "HA OS 18.3", "homeassistant": "2026.9.3", "token": "secret"},
        {"version": "2026.09.3", "healthy": True, "supported": True, "private_device": "secret"},
        {
            "state": "idle",
            "last_completed_automatic_backup": "2026-10-03T05:53:43+02:00",
            "agent_errors": {},
            "backups": [
                {
                    "backup_id": "synthetic-backup",
                    "date": "2026-10-03T03:53:43+00:00",
                    "homeassistant_included": True,
                    "database_included": True,
                    "homeassistant_version": "2026.9.3",
                    "name": "private name",
                    "extra_metadata": {"token": "secret"},
                    "agents": {"private.location": {"protected": True, "size": 12345}},
                    "failed_addons": [],
                    "failed_agent_ids": [],
                    "failed_folders": [],
                }
            ],
        },
    ]


class Socket:
    def __init__(self, messages=None):
        self.sent = []
        self.messages = (
            messages
            if messages is not None
            else [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                *[
                    {"type": "result", "id": i, "success": True, "result": v}
                    for i, v in enumerate(data(), 1)
                ],
            ]
        )

    def recv(self, *, timeout):
        assert 0 < timeout <= 8
        return json.dumps(self.messages.pop(0))

    def send(self, value):
        self.sent.append(json.loads(value))


def test_only_fixed_reads_and_minimized_inventory():
    ws = Socket()
    report = exchange(ws, "synthetic-token")
    assert ws.sent == [
        {"type": "auth", "access_token": "synthetic-token"},
        *[{"id": i, **c} for i, c in enumerate(COMMANDS, 1)],
    ]
    assert report["backup_count"] == 1 and report["backup_state"] == "idle"
    assert report["last_completed_automatic_backup"] == report["backups"][0]["created"]
    assert not any(
        word in json.dumps(report) for word in ("private", "secret", "token", "extra_metadata")
    )
    assert not report["restore_verified"] and not report["archive_integrity_verified"]
    assert not report["recovery_key_verified"] and not report["writes_enabled"]
    assert report["label"] == "LOCAL_ONLY"


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "auth_invalid", "message": "synthetic-token"},
        {"type": "result", "id": 1, "success": False, "error": {"message": "secret"}},
        {"type": "result", "id": True, "success": True, "result": {}},
        {"type": "result", "id": 999, "success": True, "result": {}},
        {"type": "event", "event": {"service": "update.install"}},
        ["unexpected"],
        {"type": "result", "data": "x" * 1_000_001},
    ],
)
def test_protocol_failure_stops_without_followup(bad):
    ws = Socket([{"type": "auth_required"}, {"type": "auth_ok"}, bad])
    with pytest.raises(ValueError):
        exchange(ws, "synthetic-token")
    assert len(ws.sent) == 2
    assert not any(c.get("method") not in (None, "get") for c in ws.sent)


@pytest.mark.parametrize(
    "field,value",
    [
        ("agents", []),
        ("date", "2026-10-03T03:53:43"),
        ("backup_id", "../file"),
        ("database_included", "true"),
        ("failed_addons", None),
    ],
)
def test_malformed_inventory_not_a_restore_proof(field, value):
    info, supervisor, backups = data()
    backups["backups"][0][field] = value
    with pytest.raises(ValueError):
        summarize(info, supervisor, backups)


@pytest.mark.parametrize("ip", ["127.0.0.1", "192.168.117.100", "169.254.169.254", "::1"])
def test_unreviewed_address_rejected_before_network(ip, monkeypatch):
    monkeypatch.setattr(
        "hub.ha_backups.socket.create_connection", lambda *a, **kw: pytest.fail("Forbidden I/O")
    )
    with pytest.raises(HTTPException) as e:
        inspect(Settings(ha_token_file="not-read", ha_allowed_ip=ip))
    assert e.value.status_code == 502


def test_pinned_transport_tls_and_no_proxy(tmp_path, monkeypatch):
    key = tmp_path / "ha-key"
    key.write_text("synthetic-token")
    key.chmod(0o600)
    sock = object()
    ws = Socket()

    def socket_connection(address, *, timeout):
        assert address == ("90.187.5.165", 443) and timeout == 8
        return nullcontext(sock)

    def connect(uri, **kw):
        assert uri == "wss://home.schlueterbusch.de/api/websocket" and kw["sock"] is sock
        assert kw["ssl"].verify_mode == ssl.CERT_REQUIRED and kw["ssl"].check_hostname
        assert kw["proxy"] is None and kw["compression"] is None
        assert kw["max_size"] == 1_000_000 and kw["max_queue"] == 2
        assert kw["logger"].disabled and kw["legacy"]
        return nullcontext(ws)

    monkeypatch.setattr("hub.ha_backups.socket.create_connection", socket_connection)
    monkeypatch.setattr("hub.ha_backups.connect", connect)
    assert (
        inspect(Settings(ha_token_file=str(key), ha_allowed_ip="90.187.5.165"))["backup_count"] == 1
    )


def test_api_strict_parameters_and_receipt_replay(gateway, monkeypatch):  # noqa: F811
    app, c, h, cfg = gateway
    calls = []

    def read(cfg):
        calls.append(True)
        return summarize(*data())

    monkeypatch.setattr("hub.action_api.inspect_ha_backups", read)
    body = {"request_id": str(uuid.uuid4()), "tool_id": "ha.backups.inspect", "parameters": {}}
    assert c.post("/api/actions", json=body).status_code == 403
    assert (
        c.post(
            "/api/actions",
            json={**body, "parameters": {"method": "post", "endpoint": "/backups/new/full"}},
            headers=h,
        ).status_code
        == 422
    )
    action = c.post("/api/actions", json=body, headers=h).json()
    result = c.post("/api/actions/" + action["id"] + "/execute", json={}, headers=h).json()
    assert result["status"] == "succeeded" and result["receipt"]["backup_count"] == 1
    assert c.post("/api/actions/" + action["id"] + "/execute", json={}, headers=h).json() == result
    assert c.get("/api/action-policy").json()["paused"] and len(calls) == 1
