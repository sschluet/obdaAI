"""User-configured read-only knowledge clients; no mounts, shell or free SQL."""

import ipaddress
import os
import re
import socket
import subprocess
import threading
import time
from collections import deque
from collections.abc import Generator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.parse import quote

import psycopg
from psycopg import sql
from pydantic import Field, field_validator, model_validator

from hub.action_api import StrictInput
from hub.extract import EXTENSIONS, MAX_BYTES


class ConnectionInput(StrictInput):
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["smb", "nfs", "sql", "obsidian"]
    server: str = Field(min_length=1, max_length=253)
    share: str = Field(default="", max_length=240)
    folder: str = Field(default="", max_length=800)
    port: int = Field(default=0, ge=0, le=65535)
    username: str = Field(default="", max_length=200)
    password: str | None = Field(default=None, max_length=4096, repr=False)
    database: str = Field(default="", max_length=100)
    schema_name: str = Field(default="public", max_length=100)
    table: str = Field(default="", max_length=100)
    tls: bool = True
    nfs_version: Literal[3, 4] = 3
    uid: int = Field(default=65534, ge=0, le=2147483647)
    gid: int = Field(default=65534, ge=0, le=2147483647)
    max_files: int = Field(default=50, ge=1, le=1000)
    max_rows: int = Field(default=100, ge=1, le=1000)
    revision: int | None = Field(default=None, ge=1)

    @field_validator("server")
    @classmethod
    def host(cls, v: str) -> str:
        v = v.strip().lower()
        try:
            ipaddress.ip_address(v)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", v):
                raise ValueError(
                    "Servername oder IP-Adresse ohne URL und Zugangsdaten eingeben"
                ) from None
        return v

    @field_validator("folder")
    @classmethod
    def path(cls, v: str) -> str:
        if "\\" in v or any(ord(c) < 32 for c in v) or ".." in PurePosixPath(v).parts:
            raise ValueError("Ungültiger Ordnerpfad")
        if any(p.startswith(".") for p in PurePosixPath(v).parts if p != "/"):
            raise ValueError("Versteckte Konfigurationsordner sind keine Wissensquelle")
        return v.strip("/")

    @model_validator(mode="after")
    def shape(self) -> "ConnectionInput":
        if self.kind in {"smb", "obsidian"} and (
            not self.share or any(c in self.share for c in "/\\\r\n")
        ):
            raise ValueError("Eine einzelne SMB-Freigabe angeben")
        if self.kind == "nfs" and not self.share.startswith("/"):
            raise ValueError("NFS-Export als absoluten Pfad angeben")
        if self.kind == "nfs" and (
            ".." in PurePosixPath(self.share).parts or any(c in self.share for c in "?\r\n\\")
        ):
            raise ValueError("Ungültiger NFS-Export")
        if self.kind == "sql" and (
            not self.database
            or not self.username
            or any(
                not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", x)
                for x in [self.schema_name, self.table]
            )
        ):
            raise ValueError("PostgreSQL-Datenbank, Benutzer, Schema und Tabelle/View angeben")
        return self

    def public(self) -> dict[str, Any]:
        return self.model_dump(exclude={"password", "revision"})


def resolve_host(host: str, port: int) -> str:
    addresses = sorted(
        {str(a[4][0]) for a in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    )
    if not addresses or any(
        ipaddress.ip_address(a).is_loopback
        or ipaddress.ip_address(a).is_link_local
        or ipaddress.ip_address(a).is_multicast
        or ipaddress.ip_address(a).is_unspecified
        or ipaddress.ip_address(a).is_reserved
        for a in addresses
    ):
        raise ValueError("Lokale System- und Metadatenadressen sind keine externen Wissensquellen")
    return next((a for a in addresses if ":" not in a), addresses[0])


@dataclass
class Document:
    path: str
    content: bytes


def safe_relative(path: str) -> bool:
    p = PurePosixPath(path)
    return (
        bool(path)
        and not p.is_absolute()
        and len(path) <= 1000
        and ".." not in p.parts
        and "\\" not in path
        and all(not part.startswith(".") for part in p.parts)
        and not any(ord(c) < 32 for c in path)
    )


def smb_documents(
    body: ConnectionInput, password: str, probe: bool
) -> Generator[Document, None, None]:
    import smbclient  # type: ignore[import-untyped]
    from smbprotocol.open import FileAttributes  # type: ignore[import-untyped]

    ip = resolve_host(body.server, body.port or 445)
    cache: dict[str, Any] = {}
    smbclient.ClientConfig(skip_dfs=True, require_secure_negotiate=True)

    def stop_private_connections() -> None:
        for connection in list(cache.values()):
            with suppress(Exception):
                connection.disconnect(close=False, timeout=1)

    timer = threading.Timer(110, stop_private_connections)
    timer.daemon = True
    timer.start()
    try:
        smbclient.register_session(
            ip,
            username=body.username,
            password=password,
            port=body.port or 445,
            encrypt=True,
            auth_protocol="ntlm",
            require_signing=True,
            connection_timeout=8,
            connection_cache=cache,
        )
        root = (
            "\\\\"
            + ip
            + "\\"
            + body.share
            + ("\\" + body.folder.replace("/", "\\") if body.folder else "")
        )
        pending = deque([""])
        inspected, imported = 0, 0
        started = time.monotonic()
        while pending and inspected < 10000 and time.monotonic() - started < 90:
            directory = pending.popleft()
            path = root + ("\\" + directory.replace("/", "\\") if directory else "")
            for entry in smbclient.scandir(path, connection_cache=cache, port=body.port or 445):
                if time.monotonic() - started >= 90:
                    raise TimeoutError("SMB indexing deadline")
                inspected += 1
                name = (directory + "/" + entry.name).lstrip("/")
                if not safe_relative(name) or inspected > 10000:
                    continue
                st = entry.stat(follow_symlinks=False)
                if st.st_file_attributes & FileAttributes.FILE_ATTRIBUTE_REPARSE_POINT:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if len(PurePosixPath(name).parts) < 9:
                        pending.append(name)
                    continue
                suffix = PurePosixPath(name).suffix.lower()
                if (
                    suffix not in EXTENSIONS
                    or (body.kind == "obsidian" and suffix != ".md")
                    or st.st_size > MAX_BYTES
                ):
                    continue
                if probe:
                    yield Document(name, b"")
                    return
                with smbclient.open_file(
                    root + "\\" + name.replace("/", "\\"),
                    mode="rb",
                    connection_cache=cache,
                    port=body.port or 445,
                ) as f:
                    content = f.read(MAX_BYTES + 1)
                if content and len(content) <= MAX_BYTES:
                    yield Document(name, content)
                    imported += 1
                if imported >= body.max_files:
                    return
        if probe:
            yield Document("", b"")  # Empty readable folder is still connected.
    finally:
        timer.cancel()
        smbclient.reset_connection_cache(connection_cache=cache, fail_on_error=False)


def nfs_output(program: str, url: str, limit: int) -> bytes:
    # Fixed read-only binaries; never a shell or user-supplied command/options.
    with subprocess.Popen([program, url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as p:
        assert p.stdout is not None
        try:
            data = bytearray()
            started = time.monotonic()
            import selectors

            with selectors.DefaultSelector() as selector:
                selector.register(p.stdout, selectors.EVENT_READ)
                while time.monotonic() - started < 15:
                    if not selector.select(timeout=1):
                        if p.poll() is not None:
                            break
                        continue
                    part = os.read(p.stdout.fileno(), 65536)
                    if not part:
                        break
                    data.extend(part)
                    if len(data) > limit:
                        raise ValueError("NFS-Antwort überschreitet Grenze")
                else:
                    raise TimeoutError("NFS read timeout")
            if p.wait(timeout=2) != 0:
                raise ValueError("NFS read failed")
            return bytes(data)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()


def nfs_documents(body: ConnectionInput, probe: bool) -> Generator[Document, None, None]:
    ip = resolve_host(body.server, 2049)
    if ipaddress.ip_address(ip).is_global:
        raise ValueError("NFS-Wissensquellen benötigen ein privates Netz")
    host = "[" + ip + "]" if ":" in ip else ip
    base = (
        "nfs://"
        + host
        + quote(body.share.rstrip("/") + ("/" + body.folder if body.folder else ""), safe="/")
    )
    args = (
        "?version="
        + str(body.nfs_version)
        + "&uid="
        + str(body.uid)
        + "&gid="
        + str(body.gid)
        + "&timeout=10000&retrans=0"
    )
    pending = deque([""])
    imported = 0
    inspected = 0
    started = time.monotonic()
    while pending and inspected < 10000 and time.monotonic() - started < 90:
        directory = pending.popleft()
        data = nfs_output(
            "nfs-ls",
            base + ("/" + quote(directory, safe="/") if directory else "") + args,
            1_000_000,
        ).decode("utf-8", errors="strict")
        if probe:
            yield Document("", b"")
            return
        for line in data.splitlines():
            fields = line.split(None, 5)
            if len(fields) != 6 or len(fields[0]) != 10:
                continue
            inspected += 1
            name = (directory + "/" + fields[5]).lstrip("/")
            if not safe_relative(name):
                continue
            if fields[0].startswith("d"):
                if len(PurePosixPath(name).parts) < 9:
                    pending.append(name)
            elif (
                fields[0].startswith("-")
                and PurePosixPath(name).suffix.lower() in EXTENSIONS
                and int(fields[4]) <= MAX_BYTES
            ):
                content = nfs_output(
                    "nfs-cat", base + "/" + quote(name, safe="/") + args, MAX_BYTES
                )
                if content:
                    yield Document(name, content)
                    imported += 1
                if imported >= body.max_files:
                    return


def sql_documents(
    body: ConnectionInput, password: str, probe: bool
) -> Generator[Document, None, None]:
    ip = resolve_host(body.server, body.port or 5432)
    if ipaddress.ip_address(ip).is_global and not body.tls:
        raise ValueError("Öffentliche SQL-Verbindungen benötigen TLS")
    with psycopg.connect(
        host=body.server,
        hostaddr=ip,
        port=body.port or 5432,
        dbname=body.database,
        user=body.username,
        password=password,
        connect_timeout=8,
        sslmode="verify-full" if body.tls else "disable",
        options="-c default_transaction_read_only=on -c statement_timeout=5000",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            query = sql.SQL(
                "SELECT left(row_to_json(t)::text,12000) FROM {}.{} AS t LIMIT %s"
            ).format(sql.Identifier(body.schema_name), sql.Identifier(body.table))
            cursor.execute(query, (1 if probe else body.max_rows + 1,))
            rows = cursor.fetchall()
            if probe:
                yield Document("", b"")
                return
            text = (
                "PostgreSQL-Momentaufnahme: "
                + body.schema_name
                + "."
                + body.table
                + "\nMaximal "
                + str(body.max_rows)
                + " Datensätze.\n\n"
                + "\n".join(row[0] for row in rows[: body.max_rows])
            )
            yield Document("SQL_" + body.table + ".txt", text.encode())
        connection.rollback()


def documents(
    body: ConnectionInput, password: str, *, probe: bool = False
) -> Generator[Document, None, None]:
    if body.kind in {"smb", "obsidian"}:
        yield from smb_documents(body, password, probe)
    elif body.kind == "nfs":
        yield from nfs_documents(body, probe)
    else:
        yield from sql_documents(body, password, probe)
