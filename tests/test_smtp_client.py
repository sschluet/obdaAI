"""SMTP transport authentication, TLS pinning and irreversible handoff boundary."""

import smtplib
from email.message import EmailMessage

import pytest
from hub import smtp_client as smtp
from hub.config import Settings


def config(port=465):
    return {
        "url": "mail.example.test",
        "port": port,
        "username": "synthetic-user",
        "sender": "sender@example.test",
    }


class Connection:
    def __init__(self, *args, **kwargs):
        self.args, self.events = args, []
        self.closed = False
        self._host = args[0] if args else ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def ehlo(self):
        self.events.append("ehlo")

    def starttls(self, *, context):
        assert context.check_hostname
        assert self._host == "mail.example.test"
        self.events.append("starttls")

    def login(self, username, password):
        self.events.append("login")

    def close(self):
        self.closed = True

    def noop(self):
        self.events.append("noop")
        return 250, b"ok"

    def mail(self, sender):
        self.events.append("mail")
        return 250, b"ok"

    def rcpt(self, recipient):
        self.events.append("rcpt")
        return 250, b"ok"

    def data(self, message):
        self.events.append("data")
        return 250, b"accepted"


@pytest.mark.parametrize("port", [465, 587])
def test_tls_authentication_pinned_numeric_connection(monkeypatch, port):
    sockets = []

    def factory(*args, **kwargs):
        value = Connection(*args, **kwargs)
        sockets.append(value)
        return value

    monkeypatch.setattr(
        smtp,
        "resolved_targets",
        lambda cfg, host, ssh_port: [("2001:db8::7", ssh_port), ("203.0.113.7", ssh_port)],
    )
    monkeypatch.setattr(smtp, "PinnedSSL", factory)
    monkeypatch.setattr(smtp.smtplib, "SMTP", factory)
    connection = smtp.connect(Settings(), config(port), "synthetic-password")
    assert connection.args == (
        ("203.0.113.7", "mail.example.test", 465) if port == 465 else ("203.0.113.7", 587)
    )
    assert connection.events == (
        ["login"] if port == 465 else ["ehlo", "starttls", "ehlo", "login"]
    )


def test_starttls_failure_never_authenticates(monkeypatch):
    connection = Connection()

    def fail(**kwargs):
        connection.events.append("starttls")
        raise smtplib.SMTPNotSupportedError("TLS unavailable")

    connection.starttls = fail
    monkeypatch.setattr(smtp, "resolved_targets", lambda *args, **kwargs: [("203.0.113.7", 587)])
    monkeypatch.setattr(smtp.smtplib, "SMTP", lambda *args, **kwargs: connection)
    with pytest.raises(ValueError):
        smtp.connect(Settings(), config(587), "synthetic")
    assert "login" not in connection.events and connection.closed


def test_465_wrap_uses_hostname_and_closes_failed_socket(monkeypatch):
    class Socket:
        closed = False

        def close(self):
            self.closed = True

    connection = Socket()
    observed = []

    class TLS:
        def wrap_socket(self, value, *, server_hostname):
            observed.append(server_hostname)
            raise OSError("certificate rejected")

    client = object.__new__(smtp.PinnedSSL)
    client.target_hostname, client.context = "mail.example.test", TLS()
    monkeypatch.setattr(smtp.socket, "create_connection", lambda *args: connection)
    with pytest.raises(OSError):
        client._get_socket("203.0.113.7", 465, 10)
    assert observed == ["mail.example.test"] and connection.closed


def test_assessment_only_auth_and_noop(monkeypatch):
    connection = Connection()
    monkeypatch.setattr(smtp, "connect", lambda *args: connection)
    assert smtp.assessment(Settings(), config(), "synthetic")["mail_sent"] is False
    assert connection.events == ["noop"] and connection.closed


@pytest.mark.parametrize(
    "address",
    [
        "a@example.test\r\nBcc: x@example.test",
        "a@example.test,b@example.test",
        "Name <a@example.test>",
        "a b@example.test",
        "a@",
    ],
)
def test_mailbox_rejects_header_injection_and_multiple_recipients(address):
    with pytest.raises(ValueError):
        smtp.mailbox(address)


def test_boundary_precedes_data_and_rejected_recipient_never_hands_off():
    message = EmailMessage()
    message["From"], message["To"] = "sender@example.test", "recipient@example.test"
    message.set_content("Synthetic result")
    connection = Connection()
    smtp.send(connection, message, lambda: connection.events.append("boundary"))
    assert connection.events == ["mail", "rcpt", "boundary", "data"]
    connection.events.clear()
    connection.rcpt = lambda recipient: (550, b"rejected")
    with pytest.raises(ValueError):
        smtp.send(connection, message, lambda: connection.events.append("boundary"))
    assert connection.events == ["mail"]


@pytest.mark.parametrize(
    "changes",
    [
        {"port": 25},
        {"sender": "sender@example.test\nBcc: evil@example.test"},
        {"url": "mail.example.test\r\n"},
        {"username": ""},
    ],
)
def test_invalid_configuration_rejected_before_connection(monkeypatch, changes):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid SMTP configuration must not resolve or connect")

    monkeypatch.setattr(smtp, "resolved_targets", forbidden)
    with pytest.raises(ValueError):
        smtp.connect(Settings(), {**config(), **changes}, "synthetic")
