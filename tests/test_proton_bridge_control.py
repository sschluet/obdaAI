"""Credential broker proves fixed readonly IMAP and one-attempt local setup."""

import importlib.util
import ssl
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "bridge_control", Path("scripts/proton_bridge_control.py")
)
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


@pytest.fixture
def control(tmp_path, monkeypatch):
    monkeypatch.setattr(broker, "ENV_FILE", tmp_path / "bridge.env")
    monkeypatch.setattr(broker, "STATE_FILE", tmp_path / "state.json")
    checks, restarts = [], []
    monkeypatch.setattr(broker, "verify_imap", lambda u, p: checks.append((u, p)))
    monkeypatch.setattr(broker.subprocess, "run", lambda args, **kw: restarts.append(args))
    return checks, restarts


def payload(**changes):
    return {
        "username": "mail@example.test",
        "password": "synthetic-password",
        "expected_revision": 0,
        "request_id": str(uuid4()),
        **changes,
    }


def test_atomic_private_env_preserve_and_replay(control):
    checks, restarts = control
    body = payload(password='synthetic "quoted" \\ $password')
    assert broker.configure(body, "synthetic-token")["connected"]
    assert broker.ENV_FILE.stat().st_mode & 0o777 == 0o600
    assert broker.STATE_FILE.stat().st_mode & 0o777 == 0o600
    assert broker.credentials() == (body["username"], body["password"])
    assert body["password"] not in broker.STATE_FILE.read_text()
    assert broker.configure(body, "synthetic-token")["revision"] == 1
    assert len(checks) == len(restarts) == 1
    assert restarts[0] == ["systemctl", "restart", "obdaai-proton-mcp"]
    assert (
        broker.configure(payload(password=None, expected_revision=1), "synthetic-token")["revision"]
        == 2
    )
    assert checks[-1][1] == body["password"]
    with pytest.raises(ValueError):
        broker.configure(
            payload(username="other@example.test", password=None, expected_revision=2),
            "synthetic-token",
        )


def test_intent_survives_restart_failure_no_replay(control, monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(broker.subprocess, "run", fail)
    body = payload()
    with pytest.raises(RuntimeError):
        broker.configure(body, "token")
    assert not broker.status()["connected"]
    assert broker.load_state()["requests"][body["request_id"]]["status"] == "dispatching"
    with pytest.raises(RuntimeError):
        broker.configure(body, "token")
    with pytest.raises(RuntimeError):
        broker.configure(payload(expected_revision=1), "token")


def test_invalid_login_preserves_originals(control, monkeypatch):
    broker.atomic_write(
        broker.ENV_FILE,
        'PROTONMAIL_BRIDGE_USERNAME="old"\nPROTONMAIL_BRIDGE_PASSWORD="old-password"\n',
    )
    before = broker.ENV_FILE.read_bytes()

    def fail(*args):
        raise ValueError("Rejected")

    monkeypatch.setattr(broker, "verify_imap", fail)
    with pytest.raises(ValueError):
        broker.configure(payload(), "token")
    assert broker.ENV_FILE.read_bytes() == before
    assert not broker.STATE_FILE.exists()


@pytest.mark.parametrize("value", ["bad\nINJECT=x", "bad\rvalue", "bad\x00value", "bad\tvalue", ""])
def test_environment_injection_rejected(value):
    with pytest.raises(ValueError):
        broker.quote_env(value)


def test_http_auth_bounds_and_no_secret_output(control, monkeypatch):
    monkeypatch.setattr("socket.getfqdn", lambda *args: "localhost")
    server = ThreadingHTTPServer(("127.0.0.1", 0), broker.handler("synthetic-secret-token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_port) + "/v1/configuration"
    headers = {"Authorization": "Bearer synthetic-secret-token"}
    try:
        with httpx.Client(trust_env=False) as client:
            assert client.get(url).status_code == 401
            assert client.get(url, headers=headers).json() == {
                "revision": 0,
                "username": "",
                "connected": False,
            }
            assert client.post(url, headers=headers, content="x" * 12001).status_code == 409
            assert (
                client.post(
                    url, headers=headers, json={**payload(), "host": "external.test"}
                ).status_code
                == 409
            )
            response = client.post(url, headers=headers, json=payload())
            assert response.status_code == 200
            assert "synthetic-password" not in response.text
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_fixed_imap_starttls_certificate_and_readonly_select(tmp_path, monkeypatch):
    # Synthetic certificate bytes only; no network connection is made.
    cert = b"synthetic-public-certificate"
    path = tmp_path / "cert.pem"
    path.write_text(ssl.DER_cert_to_PEM_cert(cert))
    monkeypatch.setattr(broker, "CERT_FILE", path)
    context = type("Context", (), {"check_hostname": True})()
    monkeypatch.setattr(broker.ssl, "create_default_context", lambda **kw: context)
    events = []

    class Client:
        def __init__(self, *args, **kw):
            events.append(("connect", args, kw))
            self.sock = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, **kw):
            events.append(("tls", kw))

        def getpeercert(self, **kw):
            return cert

        def login(self, *args):
            events.append(("login", args))
            return "OK", []

        def select(self, *args, **kw):
            events.append(("select", args, kw))
            return "OK", []

    monkeypatch.setattr(broker.imaplib, "IMAP4", Client)
    broker.verify_imap("synthetic-user", "synthetic-password")
    assert events[0] == ("connect", ("127.0.0.1", 1143), {"timeout": 8})
    assert events[-1] == ("select", ("INBOX",), {"readonly": True})
    assert events[1][0] == "tls" and events[2][0] == "login"
