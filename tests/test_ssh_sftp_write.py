"""Real SSH negotiation and SFTP against a disposable loopback-only test server."""

import os
import socket
import threading
from pathlib import Path

import paramiko
import pytest
from hub import integration_write_adapters as adapter
from hub.config import Settings


class Authentication(paramiko.ServerInterface):
    calls = 0

    def check_auth_password(self, username, password):
        Authentication.calls += 1
        return (
            paramiko.AUTH_SUCCESSFUL
            if (username, password) == ("synthetic", "synthetic-secret")
            else paramiko.AUTH_FAILED
        )

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return (
            paramiko.OPEN_SUCCEEDED
            if kind == "session"
            else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        )


class Files(paramiko.SFTPServerInterface):
    def __init__(self, server, *args, root, **kwargs):
        super().__init__(server, *args, **kwargs)
        self.root = Path(root)

    def local(self, path):
        result = (self.root / path.lstrip("/")).resolve()
        if not result.is_relative_to(self.root):
            raise PermissionError("Test root escape")
        return result

    def canonicalize(self, path):
        return "/"

    def lstat(self, path):
        try:
            return paramiko.SFTPAttributes.from_stat(self.local(path).lstat())
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    stat = lstat

    def mkdir(self, path, attr):
        try:
            self.local(path).mkdir(mode=attr.st_mode or 0o700)
            return paramiko.SFTP_OK
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def chattr(self, path, attr):
        try:
            if attr.st_mode is not None:
                self.local(path).chmod(attr.st_mode)
            return paramiko.SFTP_OK
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def open(self, path, flags, attr):
        try:
            fd = os.open(self.local(path), flags, attr.st_mode or 0o600)
            mode = "r+b" if flags & os.O_RDWR else "wb" if flags & os.O_WRONLY else "rb"
            stream = os.fdopen(fd, mode)
            handle = paramiko.SFTPHandle(flags)
            handle.readfile = handle.writefile = stream
            return handle
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def posix_rename(self, old, new):
        try:
            os.replace(self.local(old), self.local(new))
            return paramiko.SFTP_OK
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)


@pytest.fixture
def server(tmp_path, monkeypatch):
    key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.2)
    port = listener.getsockname()[1]
    stop = threading.Event()
    connections = []

    def accept():
        while not stop.is_set():
            try:
                sock, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            transport = paramiko.Transport(sock)
            connections.append(transport)
            transport.add_server_key(key)
            transport.set_subsystem_handler("sftp", paramiko.SFTPServer, Files, root=tmp_path)
            try:
                transport.start_server(server=Authentication())
            except (paramiko.SSHException, EOFError):
                transport.close()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    monkeypatch.setattr(adapter, "resolved_targets", lambda *a, **kw: [("127.0.0.1", port)])
    config = {
        "kind": "ssh",
        "url": "synthetic.example.test",
        "port": port,
        "username": "synthetic",
        "auth": "password",
        "host_key": key.get_name() + " " + key.get_base64(),
    }
    yield config, tmp_path
    stop.set()
    listener.close()
    for transport in connections:
        transport.close()
    thread.join(timeout=3)


def test_real_sftp_write_backup_and_hash(server):
    config, root = server
    cfg = Settings()
    args = {"filename": "synthetic.txt", "content": "Grüße aus dem isolierten SFTP-Test"}
    assert (
        adapter.snapshot(cfg, config, "synthetic-secret", "file.write_text", args)["exists"]
        is False
    )
    adapter.apply(cfg, config, "synthetic-secret", "file.write_text", args, "first")
    assert adapter.matches(
        "ssh",
        "file.write_text",
        args,
        adapter.snapshot(cfg, config, "synthetic-secret", "file.write_text", args),
    )
    original = (root / "obdaai-managed/synthetic.txt").read_bytes()
    args["content"] = "Zweite Version"
    adapter.apply(cfg, config, "synthetic-secret", "file.write_text", args, "second")
    assert (root / "obdaai-managed/.obdaai-before-second").read_bytes() == original
    assert (root / "obdaai-managed/synthetic.txt").read_text() == "Zweite Version"


def test_real_host_key_mismatch_stops_before_authentication(server):
    config, _ = server
    other = paramiko.RSAKey.generate(2048)
    config = {**config, "host_key": other.get_name() + " " + other.get_base64()}
    before = Authentication.calls
    with pytest.raises(paramiko.BadHostKeyException):
        with adapter.sftp(Settings(), config, "synthetic-secret"):
            pytest.fail("Host mismatch accepted")
    assert Authentication.calls == before
