"""Explicit read-only OpenRouter account metadata, never model prompts or secrets."""

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from hub.auth import require_session
from hub.config import Settings, read_secret
from hub.db import BudgetReservation, LoginSession, ProviderAccountCredential, ProviderConfig
from hub.provider_settings import decrypt, encrypt
from hub.providers import pinned_url

Authenticated = Annotated[LoginSession, Depends(require_session)]


class AccountCredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str | None = Field(default=None, min_length=1, max_length=4096, repr=False)
    clear_secret: bool = False
    expected_revision: int = Field(ge=1)
    expected_credentials_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def change(self) -> "AccountCredentialInput":
        if bool(self.api_key) == self.clear_secret:
            raise ValueError("Provide key or clear flag")
        return self


def money(value: object, *, signed: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("Invalid monetary value")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid monetary value") from None
    if (
        not result.is_finite()
        or abs(result) > Decimal("1000000000000")
        or (result < 0 and not signed)
    ):
        raise ValueError("Invalid monetary value")
    return str(result)


async def fetch_metadata(key: str, path: str) -> dict[str, Any]:
    if path not in ("/key", "/credits"):
        raise ValueError("Unknown metadata endpoint")
    # Same DNS/IP pinning and official origin as inference; redirects are forbidden.
    target, headers, extensions = pinned_url("https://openrouter.ai/v1", path, external=True)
    target = target.replace("/v1/", "/api/v1/", 1)
    headers["Authorization"] = "Bearer " + key
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", target, headers=headers, extensions=extensions) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError("Metadata response too large")
    data = json.loads(body).get("data")
    if not isinstance(data, dict):
        raise ValueError("Invalid metadata response")
    return data


def safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return "OpenRouter hat den Zugriff abgelehnt; Berechtigung des API-Schlüssels prüfen."
        if status == 429:
            return "OpenRouter-Anfragelimit erreicht; später aktualisieren."
    return "OpenRouter-Status derzeit nicht verfügbar; später aktualisieren."


def install_account_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    cache: dict[str, tuple[str, float, dict[str, object]]] = {}
    locks: dict[str, asyncio.Lock] = {}

    def provider(provider_id: str) -> ProviderConfig:
        with factory() as db:
            row = db.get(ProviderConfig, provider_id)
            if not row:
                raise HTTPException(404, "Provider nicht gefunden")
            if row.kind != "openrouter":
                raise HTTPException(422, "Kontostatus ist nur für OpenRouter verfügbar")
            return row

    def credential(row: ProviderConfig) -> str:
        if not row.enabled or not cfg.cloud_enabled or row.kind not in cfg.external_provider_kinds:
            raise ValueError("Cloud deaktiviert oder durch Serverrichtlinie gesperrt.")
        data = json.loads(row.config)
        if data.get("base_url") != "https://openrouter.ai/v1":
            raise ValueError("OpenRouter-Ziel nicht freigegeben.")
        if row.encrypted_secret:
            return decrypt(cfg, row.id, row.encrypted_secret)
        if row.id == "openrouter-default" and data.get("use_server_secret", True):
            if cfg.openrouter_key_file:
                return read_secret(cfg.openrouter_key_file)
        raise ValueError("Kein API-Schlüssel für diesen Provider konfiguriert.")

    def fingerprint(row: ProviderConfig) -> str:
        # A server secret replaced in place must invalidate cached balances too.
        try:
            secret = credential(row)
        except Exception:
            secret = ""
        with factory() as db:
            account = db.get(ProviderAccountCredential, row.id)
            account_stamp = f"{account.revision}:{account.encrypted_secret}" if account else ""
        return hashlib.sha256(
            (str(row.revision) + row.config + str(row.enabled) + secret + account_stamp).encode()
        ).hexdigest()

    def local(row: ProviderConfig) -> dict[str, object]:
        now = datetime.now(UTC)
        period = now.strftime("%Y-%m")
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with factory() as db:
            rows = list(
                db.scalars(
                    select(BudgetReservation).where(
                        BudgetReservation.provider_id == row.id, BudgetReservation.month == period
                    )
                )
            )
        measured = sum(
            (Decimal(str(r.measured)) for r in rows if r.measured is not None), Decimal(0)
        )
        reserved = sum((Decimal(str(r.ceiling)) for r in rows if r.measured is None), Decimal(0))
        daily = sum(
            (
                Decimal(str(r.measured))
                for r in rows
                if r.measured is not None and r.created >= midnight
            ),
            Decimal(0),
        )
        config = json.loads(row.config)
        return {
            "month": period,
            "month_used": money(measured + reserved),
            "month_measured": money(measured),
            "month_reserved": money(reserved),
            "month_unknown_count": sum(r.measured is None for r in rows),
            "day_measured": money(daily),
            "monthly_budget": money(config.get("monthly_budget")),
            "max_run_cost": money(config.get("max_run_cost")),
            "basis": "local_settled_or_estimated_and_reserved",
        }

    def status(row: ProviderConfig) -> dict[str, object]:
        entry = cache.get(row.id)
        valid = entry is not None and entry[0] == fingerprint(row)
        result: dict[str, object] = {
            "state": "unavailable",
            "checked_at": None,
            "stale": True,
            "error": None,
            "account": None,
            "account_error": None,
            "key": None,
        }
        if entry and valid:
            result.update(entry[2])
            result["stale"] = time.monotonic() - entry[1] >= 60
        with factory() as db:
            account = db.get(ProviderAccountCredential, row.id)
            configured = bool(account and account.encrypted_secret)
            credentials_revision = account.revision if account else 0
        return {
            "account_key_configured": configured,
            "credentials_revision": credentials_revision,
            **result,
            "provider_id": row.id,
            "revision": row.revision,
            "currency": "USD",
            "local": local(row),
        }

    @app.put("/api/providers/{provider_id}/account-status/credentials")
    def save_credentials(
        provider_id: str, body: AccountCredentialInput, session: Authenticated
    ) -> dict[str, object]:
        with factory() as db:
            if db.bind is not None and db.bind.dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            row = db.scalar(
                select(ProviderConfig).where(ProviderConfig.id == provider_id).with_for_update()
            )
            if not row:
                raise HTTPException(404, "Provider nicht gefunden")
            if row.kind != "openrouter":
                raise HTTPException(422, "Kontostatus ist nur für OpenRouter verfügbar")
            account = db.get(ProviderAccountCredential, row.id)
            revision = account.revision if account else 0
            if (
                row.revision != body.expected_revision
                or revision != body.expected_credentials_revision
            ):
                raise HTTPException(409, "Provider oder Kontostatus-Schlüssel geändert; neu laden")
            if not account:
                account = ProviderAccountCredential(provider_id=row.id, revision=0)
                db.add(account)
            try:
                account.encrypted_secret = (
                    encrypt(cfg, "account-status:" + row.id, body.api_key) if body.api_key else None
                )
            except Exception:
                raise HTTPException(
                    422, "Verschlüsselung des Kontostatus-Schlüssels nicht verfügbar"
                ) from None
            account.revision += 1
            db.commit()
        cache.pop(provider_id, None)
        return status(row)

    @app.get("/api/providers/{provider_id}/account-status")
    def get_status(provider_id: str, session: Authenticated) -> dict[str, object]:
        return status(provider(provider_id))

    @app.post("/api/providers/{provider_id}/account-status/refresh")
    async def refresh(provider_id: str, session: Authenticated) -> dict[str, object]:
        row = provider(provider_id)
        async with locks.setdefault(provider_id, asyncio.Lock()):
            row = provider(provider_id)
            stamp = fingerprint(row)
            entry = cache.get(row.id)
            if entry and entry[0] == stamp and time.monotonic() - entry[1] < 60:
                return status(row)
            result: dict[str, object] = {
                "state": "error",
                "checked_at": time.time(),
                "error": None,
                "account": None,
                "account_error": None,
                "key": None,
            }
            try:
                try:
                    key = credential(row)
                except Exception:
                    raise HTTPException(
                        409, "Cloud gesperrt oder API-Schlüssel nicht verfügbar"
                    ) from None
                info = await fetch_metadata(key, "/key")
                if "limit" not in info or "limit_remaining" not in info:
                    raise ValueError("Missing key limit metadata")
                result["key"] = {
                    field: money(info.get(field))
                    for field in (
                        "usage",
                        "usage_daily",
                        "usage_weekly",
                        "usage_monthly",
                        "limit",
                        "limit_remaining",
                    )
                }
                if isinstance(info.get("is_free_tier"), bool):
                    key_info = result["key"]
                    assert isinstance(key_info, dict)
                    key_info["is_free_tier"] = info["is_free_tier"]
                try:
                    with factory() as db:
                        account = db.get(ProviderAccountCredential, row.id)
                        account_key = (
                            decrypt(cfg, "account-status:" + row.id, account.encrypted_secret)
                            if account and account.encrypted_secret
                            else None
                        )
                    if account_key is None:
                        result["account_error"] = (
                            "Kontoguthaben benötigt einen separaten Kontostatus-Schlüssel "
                            "mit Management-Berechtigung. Schlüsselnutzung wird separat angezeigt."
                        )
                        result["state"] = "ready"
                    else:
                        credits = await fetch_metadata(account_key, "/credits")
                        total = money(credits.get("total_credits"))
                        usage = money(credits.get("total_usage"))
                        if total is None or usage is None:
                            raise ValueError("Missing account totals")
                        result["account"] = {
                            "total_credits": total,
                            "total_usage": usage,
                            "balance": money(Decimal(total) - Decimal(usage), signed=True),
                        }
                except Exception as exc:
                    result["account_error"] = safe_error(exc)
                result["state"] = "ready"
            except HTTPException:
                raise
            except Exception as exc:
                result["error"] = safe_error(exc)
            current = provider(provider_id)
            if fingerprint(current) != stamp:
                cache.pop(provider_id, None)
                raise HTTPException(409, "Provider geändert; Status erneut aktualisieren")
            cache[provider_id] = (stamp, time.monotonic(), result)
            return status(current)
