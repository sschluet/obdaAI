"""Pinned public HTML snapshot, rendered offline. No arbitrary live browser proxy."""

import base64
import hashlib
import ipaddress
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import HTTPException

from hub.config import Settings


def approved(cfg: Settings, name: str, digest: str) -> dict[str, str]:
    rules = json.loads(cfg.browser_targets_json)
    row = rules.get(name) if isinstance(rules, dict) else None
    if not isinstance(row, dict) or set(row) != {"url", "ip", "name"}:
        raise HTTPException(403, "Browserziel nicht am Server freigegeben")
    if (
        hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        != digest
    ):
        raise HTTPException(409, "Browserziel-Konfiguration geändert")
    u = urlsplit(row["url"])
    ip = ipaddress.ip_address(row["ip"])
    if (
        u.scheme != "https"
        or not u.hostname
        or u.port not in (None, 443)
        or u.username
        or u.password
        or u.query
        or u.fragment
        or not ip.is_global
        or ip.version != 4
        or "%" in row["url"]
        or "\\" in row["url"]
        or any(ord(c) < 33 or ord(c) > 126 for c in row["url"])
    ):
        raise HTTPException(403, "Browserziel benötigt geprüfte öffentliche HTTPS-Adresse")
    if not cfg.browser_request_dir or not cfg.browser_result_dir:
        raise HTTPException(503, "Isolierter Browser-Renderer noch nicht eingerichtet")
    return row


def fetch(client: httpx.Client, row: dict[str, str]) -> str:
    u = urlsplit(row["url"])
    with client.stream(
        "GET",
        "https://" + row["ip"] + (u.path or "/"),
        headers={"Host": u.hostname or "", "Accept": "text/html", "Accept-Encoding": "identity"},
        extensions={"sni_hostname": u.hostname or ""},
        follow_redirects=False,
        timeout=8,
    ) as r:
        if (
            r.status_code != 200
            or r.headers.get("Content-Encoding", "identity") != "identity"
            or r.headers.get("Content-Type", "").split(";")[0].strip() != "text/html"
        ):
            raise ValueError("Unsupported public HTML response")
        raw = bytearray()
        deadline = time.monotonic() + 10
        for part in r.iter_bytes(chunk_size=65536):
            raw.extend(part)
            if len(raw) > 1_000_000 or time.monotonic() > deadline:
                raise ValueError("Browser response exceeds limit")
        return bytes(raw).decode("utf-8", errors="strict")


def snapshot(cfg: Settings, action_id: str, params: dict[str, Any]) -> dict[str, Any]:
    row = approved(cfg, params["target_id"], params["target_sha256"])
    identifier = str(UUID(action_id))
    request = Path(cfg.browser_request_dir) / (identifier + ".json")
    result = Path(cfg.browser_result_dir) / (identifier + ".json")
    try:
        for folder in (request.parent, result.parent):
            if folder.is_symlink() or not folder.is_dir():
                raise ValueError("Invalid spool")
        if request.is_symlink() or result.is_symlink():
            raise ValueError("Invalid job")
        if not request.exists():
            with httpx.Client(verify=True, trust_env=False, follow_redirects=False) as client:
                html = fetch(client, row)
            sha = hashlib.sha256(html.encode()).hexdigest()
            body = json.dumps({"id": identifier, "html": html, "sha256": sha}, ensure_ascii=False)
            if len(body.encode()) > 1_100_000:
                raise ValueError("Job limit")
            # Private immutable job: restart resumes this snapshot without re-fetching.
            temporary = request.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as file:
                file.write(body)
            os.link(temporary, request, follow_symlinks=False)
            temporary.unlink()
        if request.stat().st_size > 1_100_000:
            raise ValueError("Job limit")
        job = json.loads(request.read_text())
        if (
            job["id"] != identifier
            or hashlib.sha256(job["html"].encode()).hexdigest() != job["sha256"]
        ):
            raise ValueError("Job changed")
        until = time.monotonic() + 25
        while not result.exists():
            if time.monotonic() > until:
                raise HTTPException(
                    504,
                    "Browser-Renderer antwortet noch nicht; gleiche Aktion später erneut prüfen",
                )
            time.sleep(0.1)
        if result.is_symlink() or result.stat().st_size > 3_000_000:
            raise ValueError("Result limit")
        data = json.loads(result.read_text())
        if (
            data.get("error")
            or data.get("id") != identifier
            or data.get("sha256") != job["sha256"]
            or data.get("network") is not False
            or data.get("javascript") is not False
        ):
            raise ValueError("Invalid result")
        text = data["text"]
        png = base64.b64decode(data["png"], validate=True)
        if (
            not isinstance(text, str)
            or len(text) > 64000
            or len(png) > 2_000_000
            or not png.startswith(b"\x89PNG\r\n\x1a\n")
        ):
            raise ValueError("Invalid preview")
        return {
            "target_id": params["target_id"],
            "name": row["name"],
            "url": row["url"],
            "html_sha256": job["sha256"],
            "text": text,
            "png": data["png"],
            "label": "LOCAL_ONLY",
            "untrusted": True,
            "automatic_model_context": False,
            "live_interaction": False,
            "javascript": False,
            "renderer_network": False,
        }
    except (ValueError, OSError, KeyError, TypeError, RecursionError, httpx.HTTPError):
        raise HTTPException(
            502, "Browserprüfung gestoppt; keine automatische Weiterleitung"
        ) from None
