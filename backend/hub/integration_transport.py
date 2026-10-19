"""Human-configured integration targets, pinned before credentials are transmitted.

This policy is used only by the integration registry, never by arbitrary model URLs,
web research, source connectors or existing operator-bound maintenance tools.
"""

import ipaddress
import json
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.config import Settings
from hub.integrations import Integration


def canonical_url(value: str) -> str:
    u = urlsplit(value)
    if (
        u.scheme not in {"https", "http"}
        or not u.hostname
        or u.username is not None
        or u.password is not None
        or u.query
        or u.fragment
        or "\\" in value
        or "%" in value
        or any(ord(c) < 33 or ord(c) > 126 for c in value)
        or u.path.startswith("//")
        or any(part in {".", ".."} for part in u.path.split("/"))
    ):
        raise ValueError("Invalid integration endpoint")
    port = u.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid integration port")
    host = u.hostname.lower().rstrip(".")
    if not host:
        raise ValueError("Invalid integration host")
    try:
        ip = ipaddress.ip_address(host)
        host = f"[{ip}]" if ip.version == 6 else str(ip)
    except ValueError:
        if not all(part and len(part) <= 63 for part in host.split(".")):
            raise ValueError("Invalid integration host") from None
    explicit_port = "" if port in {None, 443 if u.scheme == "https" else 80} else f":{port}"
    # Only the root slash is an origin alias. MCP endpoint paths may deliberately
    # end in a slash and must never rely on credential-bearing redirect following.
    path = "" if u.path == "/" else u.path
    return f"{u.scheme}://{host}{explicit_port}{path}"


def permitted_address(value: str) -> bool:
    a = ipaddress.ip_address(value)
    if a.version == 6 and a.ipv4_mapped:
        return permitted_address(str(a.ipv4_mapped))
    return not (
        a.is_loopback
        or a.is_link_local
        or a.is_multicast
        or a.is_unspecified
        or a.is_reserved
        or str(a) in {"100.100.100.200", "fd00:ec2::254"}  # Instance metadata.
    )


def policy_allows(cfg: Settings, value: str, *, ssh: bool = False) -> bool:
    if not cfg.integration_targets_enabled:
        return False
    try:
        host = value if ssh else urlsplit(canonical_url(value)).hostname or ""
        if host.lower().rstrip(".") == "localhost" or host.lower().endswith(".localhost"):
            return False
        try:
            return permitted_address(host)
        except ValueError:
            return bool(host)
    except (ValueError, TypeError):
        return False


def resolved_targets(
    cfg: Settings, value: str, *, ssh_port: int | None = None
) -> list[tuple[str, int]]:
    if not policy_allows(cfg, value, ssh=ssh_port is not None):
        raise ValueError("Integration network target unavailable")
    u = urlsplit(canonical_url(value)) if ssh_port is None else None
    host = u.hostname if u else value
    if ssh_port is not None:
        port = ssh_port
    else:
        assert u is not None
        port = u.port or (443 if u.scheme == "https" else 80)
    if port is None or not 1 <= port <= 65535:
        raise ValueError("Invalid integration port")
    addresses = sorted(
        {str(item[4][0]) for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    )
    if not addresses or len(addresses) > 32 or any(not permitted_address(a) for a in addresses):
        raise ValueError("Unsafe integration DNS result")
    # Plain HTTP is useful for self-hosted LAN appliances, never for public hosts.
    if u and u.scheme == "http" and any(ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("Public integration targets require HTTPS")
    return [(address, port) for address in addresses]


def pinned_target(cfg: Settings, value: str) -> tuple[str, dict[str, str], dict[str, str]]:
    canonical = canonical_url(value)
    u = urlsplit(canonical)
    targets = resolved_targets(cfg, canonical)
    # Prefer IPv4 where available, retaining full validation of every DNS answer.
    address, port = sorted(targets, key=lambda row: ipaddress.ip_address(row[0]).version)[0]
    ip = ipaddress.ip_address(address)
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    suffix = "" if port == (443 if u.scheme == "https" else 80) else f":{port}"
    return (
        f"{u.scheme}://{host}{suffix}{u.path}",
        {"Host": u.netloc},
        {"sni_hostname": u.hostname or ""},
    )


def requests_plan(factory: sessionmaker[Session], cfg: Settings) -> list[dict[str, Any]]:
    """Numeric egress plan from enabled user profiles; never include credentials."""
    if not cfg.integration_targets_enabled:
        return []
    with factory() as db:
        rows = list(db.scalars(select(Integration).where(
            Integration.enabled.is_(True) | (Integration.kind == "gmail")
        ).limit(200)))
        plan = []
        for row in rows:
            try:
                config = json.loads(row.config)
                if row.kind == "gmail":
                    from hub.gmail_client import API_BASE, TOKEN_URL

                    if config.get("url") != API_BASE or config.get("auth") != "oauth":
                        continue
                    if not row.enabled and config.get("oauth_pending_until", 0) <= time.time():
                        continue
                    targets = resolved_targets(cfg, API_BASE) + resolved_targets(cfg, TOKEN_URL)
                    plan.append({"id": row.id, "kind": row.kind, "targets": sorted(set(targets))})
                    continue
                targets = resolved_targets(
                    cfg,
                    config["url"],
                    ssh_port=config["port"] if row.kind in {"ssh", "smtp"} else None,
                )
                plan.append({"id": row.id, "kind": row.kind, "targets": targets})
            except (ValueError, OSError, KeyError, TypeError):
                continue
        return plan
