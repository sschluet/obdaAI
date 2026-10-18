#!/usr/bin/env python3
"""Root-owned, loopback-only Bridge credential broker; never accepts account logins.

Install outside the application container. Only its bearer-authenticated fixed
operation can replace Bridge credentials and restart the fixed read-only MCP unit.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import imaplib
import json
import os
import ssl
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID

ENV_FILE = Path("/etc/obdaai/proton/bridge.env")
STATE_FILE = Path("/var/lib/obdaai-proton-control/state.json")
CERT_FILE = Path("/opt/obdaai-proton-mcp/bridge-cert.pem")
LOCK = threading.Lock()


def atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(value)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def quote_env(value: str) -> str:
    if not value or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Invalid credential")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def credentials() -> tuple[str, str]:
    if not ENV_FILE.exists():
        return "", ""
    if ENV_FILE.is_symlink() or ENV_FILE.stat().st_mode & 0o077:
        raise ValueError("Unsafe credential file")
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        key, _, raw = line.partition("=")
        if key in {"PROTONMAIL_BRIDGE_USERNAME", "PROTONMAIL_BRIDGE_PASSWORD"}:
            # This broker and the original helper emit quoted values only.
            values[key] = json.loads(raw)
    return values.get("PROTONMAIL_BRIDGE_USERNAME", ""), values.get(
        "PROTONMAIL_BRIDGE_PASSWORD", ""
    )


def verify_imap(username: str, password: str) -> None:
    context = ssl.create_default_context(cafile=str(CERT_FILE))
    context.check_hostname = False
    pinned = ssl.PEM_cert_to_DER_cert(CERT_FILE.read_text())
    with imaplib.IMAP4("127.0.0.1", 1143, timeout=8) as client:
        client.starttls(ssl_context=context)
        if not hmac.compare_digest(client.sock.getpeercert(binary_form=True), pinned):
            raise ValueError("Bridge certificate changed")
        if client.login(username, password)[0] != "OK":
            raise ValueError("Bridge login failed")
        if client.select("INBOX", readonly=True)[0] != "OK":
            raise ValueError("Bridge mailbox unavailable")


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"revision": 0, "username": "", "connected": False, "requests": {}}
    if STATE_FILE.is_symlink() or STATE_FILE.stat().st_mode & 0o077:
        raise ValueError("Unsafe broker state")
    return json.loads(STATE_FILE.read_text())


def status() -> dict[str, Any]:
    state = load_state()
    return {key: state[key] for key in ("revision", "username", "connected")}


def configure(body: dict[str, Any], token: str) -> dict[str, Any]:
    if set(body) != {"username", "password", "expected_revision", "request_id"}:
        raise ValueError("Invalid fields")
    username, password = body["username"], body["password"]
    if not isinstance(username, str) or not isinstance(password, (str, type(None))):
        raise ValueError("Invalid credentials")
    quote_env(username)
    if len(username) > 254 or username != username.strip():
        raise ValueError("Invalid username")
    request_id = str(UUID(body["request_id"]))
    if type(body["expected_revision"]) is not int or body["expected_revision"] < 0:
        raise ValueError("Invalid revision")
    if password:
        quote_env(password)
    fingerprint = hmac.new(
        token.encode(), json.dumps(body, sort_keys=True).encode(), hashlib.sha256
    ).hexdigest()
    with LOCK:
        state = load_state()
        previous = state["requests"].get(request_id)
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise ValueError("Request changed")
            if previous["status"] != "succeeded":
                raise RuntimeError("Previous attempt failed or uncertain; no replay")
            if previous["revision"] != state["revision"]:
                raise ValueError("Request superseded")
            return status()
        if state["revision"] != body["expected_revision"]:
            raise ValueError("Revision changed")
        if any(r["status"] == "dispatching" for r in state["requests"].values()):
            raise RuntimeError("Uncertain previous configuration; operator reconciliation required")
        old_user, old_password = credentials()
        if not password:
            if old_user != username or not old_password:
                raise ValueError("Password required for this username")
            password = old_password
        verify_imap(username, password)
        state["revision"] += 1
        state["connected"] = False
        state["requests"][request_id] = {
            "fingerprint": fingerprint,
            "status": "dispatching",
            "revision": state["revision"],
        }
        atomic_write(STATE_FILE, json.dumps(state))
        try:
            atomic_write(
                ENV_FILE,
                "PROTONMAIL_BRIDGE_HOST=127.0.0.1\nPROTONMAIL_BRIDGE_USERNAME="
                + quote_env(username)
                + "\nPROTONMAIL_BRIDGE_PASSWORD="
                + quote_env(password)
                + "\n",
            )
            subprocess.run(
                ["systemctl", "restart", "obdaai-proton-mcp"],
                check=True,
                timeout=20,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            # Persisted dispatching is intentionally not replayable after uncertainty.
            raise RuntimeError(
                "Configuration uncertain; operator reconciliation required"
            ) from None
        state["username"], state["connected"] = username, True
        state["requests"][request_id]["status"] = "succeeded"
        atomic_write(STATE_FILE, json.dumps(state))
        return status()


def handler(token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def respond(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def authorized(self) -> bool:
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self) -> None:
            if not self.authorized():
                self.respond(401, {"error": "Unauthorized"})
            elif self.path != "/v1/configuration":
                self.respond(404, {"error": "Not found"})
            else:
                try:
                    with LOCK:
                        self.respond(200, status())
                except Exception:
                    self.respond(503, {"error": "Broker state unavailable"})

        def do_POST(self) -> None:
            if not self.authorized():
                self.respond(401, {"error": "Unauthorized"})
                return
            try:
                if self.path != "/v1/configuration" or self.headers.get("Transfer-Encoding"):
                    raise ValueError("Invalid request")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 12000:
                    raise ValueError("Body limit")
                self.connection.settimeout(5)
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("Invalid body")
                self.respond(200, configure(body, token))
            except (ValueError, TypeError, imaplib.IMAP4.error):
                self.respond(409, {"error": "Bridge credentials or revision rejected"})
            except Exception:
                self.respond(503, {"error": "Bridge configuration failed; no automatic retry"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Broker requires root")
    if args.token_file.is_symlink() or args.token_file.stat().st_mode & 0o077:
        raise SystemExit("Token must be private")
    token = args.token_file.read_text().strip()
    if not 32 <= len(token) <= 4096 or any(not 33 <= ord(c) <= 126 for c in token):
        raise SystemExit("Invalid token")
    server = ThreadingHTTPServer(("127.0.0.1", 18765), handler(token))
    server.serve_forever()


if __name__ == "__main__":
    main()
