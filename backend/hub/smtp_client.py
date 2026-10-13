"""Pinned TLS-only SMTP; no implicit retries or automatic deliveries."""

import ipaddress
import re
import smtplib
import socket
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from typing import Any, cast

from hub.config import Settings
from hub.integration_transport import resolved_targets


def mailbox(value: str) -> str:
    if len(value) > 254 or not re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value
    ):
        raise ValueError("Eine einzelne gültige Mailadresse angeben")
    return value


def validate_host(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", value):
        raise ValueError("SMTP benötigt einen Servernamen oder eine IP-Adresse")


class PinnedSSL(smtplib.SMTP_SSL):
    def __init__(self, address: str, hostname: str, port: int):
        self.target_hostname = hostname
        super().__init__(
            address,
            port,
            timeout=10,
            local_hostname="obdaai.local",
            context=ssl.create_default_context(),
        )

    def _get_socket(self, host: str, port: int, timeout: float) -> Any:
        connection = socket.create_connection((host, port), timeout)
        try:
            return self.context.wrap_socket(connection, server_hostname=self.target_hostname)
        except Exception:
            connection.close()
            raise


def connect(cfg: Settings, config: dict[str, Any], password: str) -> smtplib.SMTP:
    try:
        hostname, port = config["url"], config["port"]
        validate_host(hostname)
        mailbox(config["sender"])
        if port not in {465, 587} or not password or not config["username"]:
            raise ValueError("Invalid SMTP configuration")
        targets = resolved_targets(cfg, hostname, ssh_port=port)
        address, _ = sorted(targets, key=lambda item: ipaddress.ip_address(item[0]).version)[0]
        connection: smtplib.SMTP
        if port == 465:
            connection = PinnedSSL(address, hostname, port)
        else:
            connection = smtplib.SMTP(address, port, timeout=10, local_hostname="obdaai.local")
            cast(Any, connection)._host = hostname
            try:
                connection.ehlo()
                connection.starttls(context=ssl.create_default_context())
                connection.ehlo()
            except Exception:
                connection.close()
                raise
        try:
            connection.login(config["username"], password)
            return connection
        except Exception:
            connection.close()
            raise
    except (OSError, smtplib.SMTPException, ValueError, KeyError):
        raise ValueError("SMTP-Verbindung oder Zugang prüfen") from None


def assessment(cfg: Settings, config: dict[str, Any], password: str) -> dict[str, Any]:
    with connect(cfg, config, password) as connection:
        code, _ = connection.noop()
        if code != 250:
            raise ValueError("SMTP-Prüfung abgewiesen")
    return {"tls": True, "authenticated": True, "mail_sent": False}


def send(connection: smtplib.SMTP, message: EmailMessage, boundary: Callable[[], None]) -> None:
    sender, recipient = mailbox(str(message["From"])), mailbox(str(message["To"]))
    if connection.mail(sender)[0] != 250 or connection.rcpt(recipient)[0] not in {250, 251}:
        raise ValueError("SMTP-Empfänger abgewiesen")
    boundary()
    code, _ = connection.data(message.as_bytes(policy=SMTP_POLICY))
    if code != 250:
        raise ValueError("SMTP-Übernahme nicht bestätigt")
