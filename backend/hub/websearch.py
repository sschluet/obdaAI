"""Replaceable SearXNG adapter: only the separately approved exact public query leaves."""

import ipaddress
import json
import re
import socket
import time
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hub.web_settings import WebOptions
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.config import Settings
from hub.db import Project, Research
from hub.db_locks import ownership_lock
from hub.knowledge_api import Auth
from hub.policy import CloudGrant, ContextPart, Privacy, check_egress


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    query: str = Field(min_length=1, max_length=500)
    public_query_approved: bool = False


def target(cfg: Settings) -> tuple[str, dict[str, str], dict[str, str]]:
    u = urlsplit(cfg.search_url)
    if (
        u.scheme not in {"http", "https"}
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
        or u.path != "/search"
    ):
        raise ValueError("Suchanbieter nicht konfiguriert")
    addresses = {
        a[4][0] for a in socket.getaddrinfo(u.hostname, u.port or 443, type=socket.SOCK_STREAM)
    }
    if not addresses or addresses != {cfg.search_allowed_ip}:
        raise ValueError("Suchanbieter-Adresse nicht freigegeben")
    ip = ipaddress.ip_address(cfg.search_allowed_ip)
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise ValueError("Verbotener Suchanbieter")
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    port = f":{u.port}" if u.port else ""
    return f"{u.scheme}://{host}{port}/search", {"Host": u.netloc}, {"sni_hostname": u.hostname}


async def search(
    cfg: Settings, request: SearchInput, *, options: "WebOptions | None" = None
) -> list[dict[str, Any]]:
    from hub.web_settings import WebOptions

    options = options or WebOptions()
    if not options.enabled:
        raise ValueError("Webrecherche ist in den Einstellungen deaktiviert")
    query = ContextPart(
        content=request.query,
        source_id=request.request_id,
        revision=1,
        label=Privacy.CLOUD_ALLOWED if request.public_query_approved else Privacy.LOCAL_ONLY,
    )
    check_egress(
        [query],
        external=True,
        provider_id="websearch",
        grants=[CloudGrant(source_id=request.request_id, revision=1, provider_id="websearch")]
        if request.public_query_approved
        else [],
    )
    url, headers, extensions = target(cfg)
    async with httpx.AsyncClient(
        timeout=options.timeout, follow_redirects=False, trust_env=False
    ) as client:
        async with client.stream(
            "GET",
            url,
            headers=headers,
            extensions=extensions,
            params={
                "q": query.content,
                "format": "json",
                "language": options.language,
                "safesearch": options.safe_search,
            },
        ) as response:
            response.raise_for_status()
            data = bytearray()
            async for part in response.aiter_bytes():
                if len(data) + len(part) > 1_000_000:
                    raise ValueError("Suchergebnis zu groß")
                data.extend(part)
    parsed = json.loads(data)
    result = []
    sites = {
        host.casefold() for host in re.findall(r"(?:^|\s)site:([a-z0-9.-]+)", request.query, re.I)
    }
    for item in parsed.get("results", [])[:100]:
        u = urlsplit(item.get("url", ""))
        if u.scheme != "https" or not u.hostname or u.username or u.password:
            continue
        if sites and not any(
            u.hostname.casefold() == host or u.hostname.casefold().endswith("." + host)
            for host in sites
        ):
            continue
        result.append(
            {
                "url": item["url"][:2048],
                "title": str(item.get("title", ""))[:300],
                "content": str(item.get("content", ""))[:4000],
                "retrieved_at": time.time(),
                "provider": "searxng",
            }
        )
        if len(result) >= options.max_results:
            break
    return result


class PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


class FetchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_index: int = Field(ge=0, le=9)
    public_url_approved: bool = False


async def fetch_page(
    cfg: Settings, url: str, approved: bool, *, user_selected: bool = False
) -> str:
    if not approved:
        raise PermissionError("URL nicht freigegeben")
    u = urlsplit(url)
    domains = json.loads(cfg.web_domains_json)
    if (
        u.scheme != "https"
        or not u.hostname
        or (not user_selected and u.hostname not in domains)
        or u.username
        or u.password
        or u.query
        or u.fragment
        or u.port not in {None, 443}
    ):
        raise ValueError("URL-Domain nicht freigegeben; keine Seite abgerufen")
    addresses = sorted(
        {a[4][0] for a in socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)}
    )
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("Private oder unzulässige Quelladresse")
    first = str(addresses[0])
    address = "[" + first + "]" if ":" in first else first
    pinned = "https://" + address + (u.path or "/")
    async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
        async with client.stream(
            "GET",
            pinned,
            headers={"Host": u.hostname or ""},
            extensions={"sni_hostname": u.hostname or ""},
        ) as response:
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("Nur öffentliche HTML-Quellen erlaubt")
            content = bytearray()
            async for part in response.aiter_bytes():
                if len(content) + len(part) > 1_000_000:
                    raise ValueError("Webseite zu groß")
                content.extend(part)
    parser = PageText()
    parser.feed(content.decode("utf-8", errors="replace"))
    return "\n".join(parser.parts)[:20000]


def install_web_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/websearch/status")
    def status(auth: Auth) -> dict[str, Any]:
        from hub.web_settings import endpoint, read_options

        with factory() as db:
            enabled = read_options(db)["enabled"]
        return {
            "configured": bool(endpoint(cfg)) and enabled,
            "enabled": enabled,
            "provider": "searxng",
            "privacy": "Nur ausdrücklich freigegebene öffentliche Suchtexte",
        }

    @app.get("/api/projects/{project_id}/research")
    def listing(project_id: str, auth: Auth) -> list[dict[str, Any]]:
        with factory() as db:
            return [
                {
                    "id": row.id,
                    "query": row.query,
                    "results": json.loads(row.results),
                    "created": row.created,
                }
                for row in db.scalars(
                    select(Research)
                    .where(Research.project_id == project_id)
                    .order_by(Research.created.desc())
                    .limit(50)
                )
            ]

    @app.post("/api/projects/{project_id}/research")
    async def research(project_id: str, body: SearchInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            project = db.get(Project, project_id)
            if not project or project.archived:
                raise HTTPException(404, "Aktives Projekt nicht gefunden")
            old = db.get(Research, body.request_id)
            if old:
                if old.project_id != project_id or old.query != body.query:
                    raise HTTPException(409, "Recherche-ID anders verwendet")
                return {"id": old.id, "query": old.query, "results": json.loads(old.results)}
        from hub.web_settings import WebOptions, read_options

        with factory() as db:
            options = read_options(db)
        options.pop("revision")
        if not options["enabled"]:
            raise HTTPException(409, "Webrecherche ist in den Einstellungen deaktiviert")
        try:
            result = await search(cfg, body, options=WebOptions.model_validate(options))
        except PermissionError:
            raise HTTPException(403, "Suchtext nicht für externe Websuche freigegeben") from None
        except (ValueError, OSError, httpx.HTTPError):
            raise HTTPException(
                409, "Keine aktuelle Recherche: Suchzugang nicht verfügbar"
            ) from None
        with factory() as db:
            ownership_lock(db)
            project = db.get(Project, project_id)
            if not project or project.archived:
                raise HTTPException(404, "Aktives Projekt nicht gefunden")
            row = Research(
                id=body.request_id,
                project_id=project_id,
                query=body.query,
                results=json.dumps(result),
            )
            db.add(row)
            db.commit()
            return {"id": row.id, "query": row.query, "results": result}

    @app.post("/api/projects/{project_id}/research/{research_id}/fetch")
    async def fetch(
        project_id: str, research_id: str, body: FetchInput, auth: Auth
    ) -> dict[str, Any]:
        with factory() as db:
            row = db.get(Research, research_id)
            if not row or row.project_id != project_id:
                raise HTTPException(404, "Recherche im Projekt nicht gefunden")
            results = json.loads(row.results)
            if body.result_index >= len(results):
                raise HTTPException(404, "Quelle nicht gefunden")
            item = results[body.result_index]
        try:
            text = await fetch_page(cfg, item["url"], body.public_url_approved)
        except PermissionError:
            raise HTTPException(403, "Quellabruf nicht freigegeben") from None
        except (ValueError, OSError, httpx.HTTPError):
            raise HTTPException(
                409, "Quelle nicht abrufbar; Domainfreigabe oder Netzwerk prüfen"
            ) from None
        item.update(fetched_text=text, fetched_at=time.time())
        with factory() as db:
            ownership_lock(db)
            row = db.scalar(select(Research).where(Research.id == research_id).with_for_update())
            if row is None or row.project_id != project_id:
                raise HTTPException(404, "Recherche im Projekt nicht mehr verfügbar")
            current = json.loads(row.results)
            if current[body.result_index]["url"] != item["url"]:
                raise HTTPException(409, "Recherche inzwischen geändert")
            current[body.result_index] = item
            row.results = json.dumps(current)
            db.commit()
        return dict(item)
