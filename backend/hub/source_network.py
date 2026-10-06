"""Only authenticated source forms create short-lived transport leases, never model tools."""

import asyncio
import ipaddress
import json
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.config import Settings
from hub.db import SourceNetworkRequest


async def request_network(
    factory: sessionmaker[Session], cfg: Settings, kind: str, config: dict[str, Any]
) -> None:
    if not cfg.source_network_enabled:
        return
    with factory() as db:
        row = SourceNetworkRequest(kind=kind, config=json.dumps(config), expires=time.time() + 300)
        db.add(row)
        db.commit()
        rid = row.id
    try:
        async with asyncio.timeout(15):
            while True:
                with factory() as db:
                    current = db.get(SourceNetworkRequest, rid)
                    if current and current.granted and current.expires > time.time():
                        return
                await asyncio.sleep(0.2)
    except TimeoutError:
        raise ValueError("Die Quellen-Netzwerkfreigabe ist noch nicht bestätigt") from None


def lease_targets(kind: str, config: dict[str, Any]) -> list[tuple[str, int]]:
    if kind == "website":
        u = urlsplit(config.get("url", ""))
        if (
            u.scheme != "https"
            or not u.hostname
            or u.username
            or u.password
            or u.query
            or u.fragment
            or u.port not in {None, 443}
        ):
            return []
        host, port = u.hostname, 443
    elif kind in {"smb", "obsidian", "sql", "nfs"}:
        host = config.get("server", "")
        port = int(
            config.get("port") or (5432 if kind == "sql" else 445 if kind != "nfs" else 2049)
        )
        if not isinstance(host, str) or not 1 <= port <= 65535:
            return []
    else:
        return []
    addresses = {str(a[4][0]) for a in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    if not addresses:
        return []
    parsed = [ipaddress.ip_address(a) for a in addresses]
    if any(
        a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified or a.is_reserved
        for a in parsed
    ):
        return []
    if kind == "website" and any(not a.is_global for a in parsed):
        return []
    if kind == "nfs" and any(a.is_global for a in parsed):
        return []
    ports = [111, 2049] if kind == "nfs" else [port]
    return [(str(a), p) for a in parsed for p in ports]


def requests_plan(factory: sessionmaker[Session]) -> list[dict[str, Any]]:
    with factory() as db:
        rows = list(
            db.scalars(
                select(SourceNetworkRequest)
                .where(SourceNetworkRequest.expires > time.time())
                .limit(200)
            )
        )
        plan = []
        for row in rows:
            try:
                targets = lease_targets(row.kind, json.loads(row.config))
                plan.append({"id": row.id, "kind": row.kind, "targets": targets})
            except (ValueError, OSError):
                pass
        return plan


def grant(factory: sessionmaker[Session], ids: list[str]) -> None:
    with factory() as db:
        for row in db.scalars(
            select(SourceNetworkRequest).where(
                SourceNetworkRequest.id.in_(ids), SourceNetworkRequest.expires > time.time()
            )
        ):
            row.granted = True
        db.commit()
