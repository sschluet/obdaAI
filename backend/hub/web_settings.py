"""Persistent research options; transport and DNS pins remain server controlled."""

from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput
from hub.config import Settings
from hub.db import WebSettings
from hub.knowledge_api import Auth
from hub.skill_api import lock


class WebOptions(StrictInput):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = True
    language: Literal["all", "de", "en"] = "all"
    safe_search: int = Field(default=1, ge=0, le=2)
    max_results: int = Field(default=8, ge=1, le=8)
    timeout: int = Field(default=15, ge=5, le=30)


class WebSettingsInput(WebOptions):
    revision: int = Field(ge=0)


def read_options(db: Session) -> dict[str, Any]:
    row = db.get(WebSettings, 1)
    if row is None:
        return {"revision": 0, **WebOptions().model_dump()}
    return {
        "revision": row.revision,
        **WebOptions.model_validate(
            {name: getattr(row, name) for name in WebOptions.model_fields}
        ).model_dump(),
    }


def endpoint(cfg: Settings) -> str:
    try:
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
            return ""
        _ = u.port
        return cfg.search_url
    except ValueError:
        return ""


def view(db: Session, cfg: Settings) -> dict[str, Any]:
    return {
        **read_options(db),
        "configured": bool(endpoint(cfg)),
        "endpoint": endpoint(cfg),
        "endpointEditable": False,
    }


def install_web_settings_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/web-settings")
    def get(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return view(db, cfg)

    @app.put("/api/web-settings")
    def put(body: WebSettingsInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            current = read_options(db)
            if current["revision"] != body.revision:
                raise HTTPException(409, "Webrecherche inzwischen geändert; neu laden")
            row = db.get(WebSettings, 1)
            if row is None:
                row = WebSettings(id=1)
                db.add(row)
            for name, value in body.model_dump(exclude={"revision"}).items():
                setattr(row, name, value)
            row.revision = body.revision + 1
            db.commit()
            return view(db, cfg)

    @app.post("/api/web-settings/test")
    async def test(auth: Auth) -> dict[str, Any]:
        from hub.websearch import SearchInput, search

        with factory() as db:
            options = read_options(db)
        # Deliberate user test may check a disabled provider without enabling it.
        options.pop("revision")
        options["enabled"] = True
        try:
            result = await search(
                cfg,
                SearchInput(
                    request_id=str(uuid4()),
                    query="SearXNG public search documentation",
                    public_query_approved=True,
                ),
                options=WebOptions.model_validate(options),
            )
        except (ValueError, OSError, PermissionError, httpx.HTTPError):
            return {
                "success": False,
                "source_count": 0,
                "message": "Suchzugang nicht erreichbar; Serverkonfiguration prüfen",
            }
        return {
            "success": bool(result),
            "source_count": len(result),
            "message": "Suchzugang erreichbar"
            if result
            else "Keine Ergebnisse beim Verbindungstest",
        }
