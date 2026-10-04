"""Versioned provider configuration. Network permissions remain server-owned."""

import base64
import json
import os
import time
from dataclasses import replace
from decimal import Decimal
from typing import Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.budgets import ExecutionLimitError
from hub.config import Settings, read_secret
from hub.db import ProviderConfig, ProviderRevision
from hub.providers import Providers, pinned_url


class ProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["local", "openrouter"]
    base_url: str = Field(max_length=400)
    model: str = Field(max_length=240)
    enabled: bool = True
    is_default: bool = False
    capabilities: list[Literal["text", "vision", "tools", "structured", "embeddings", "images"]] = (
        Field(default=["text"], max_length=6)
    )
    allowed_labels: list[Literal["LOCAL_ONLY", "CLOUD_ALLOWED"]] = Field(
        default=["LOCAL_ONLY"], max_length=2
    )
    context_tokens: int = Field(default=32768, ge=256, le=2000000)
    context_chars: int = Field(default=24000, ge=256, le=24000)
    output_tokens: int = Field(default=2048, ge=16, le=8192)
    timeout: int = Field(default=30, ge=5, le=60)
    monthly_budget: float = Field(default=0, ge=0, le=1000, allow_inf_nan=False)
    max_run_cost: float = Field(default=0, ge=0, le=10, allow_inf_nan=False)
    disable_thinking: bool = False
    revision: int | None = Field(default=None, ge=1)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096, repr=False)
    clear_secret: bool = False

    @model_validator(mode="after")
    def validate_classes(self) -> "ProviderInput":
        if len(set(self.capabilities)) != len(self.capabilities) or not self.allowed_labels:
            raise ValueError("Duplicate capabilities or empty privacy classes")
        if self.kind == "openrouter" and "LOCAL_ONLY" in self.allowed_labels:
            raise ValueError("External provider cannot accept LOCAL_ONLY")
        if self.api_key and self.clear_secret:
            raise ValueError("Cannot replace and clear a secret together")
        return self


def local_endpoints(cfg: Settings) -> dict[str, str]:
    values = json.loads(cfg.local_endpoints_json)
    if not isinstance(values, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in values.items()
    ):
        raise ValueError("Invalid server endpoint allowlist")
    if cfg.local_base_url:
        values[cfg.local_base_url] = cfg.local_allowed_ip
    return values


def validate_endpoint(body: ProviderInput, cfg: Settings) -> None:
    if body.kind == "openrouter":
        if body.base_url != "https://openrouter.ai/v1":
            raise ValueError("OpenRouter requires the official endpoint")
    else:
        approved = local_endpoints(cfg)
        if body.base_url not in approved:
            raise ValueError("Local endpoint is not in the server allowlist")
        pinned_url(body.base_url, "/models", external=False, allowed_ip=approved[body.base_url])


def cipher(cfg: Settings) -> AESGCM:
    if not cfg.secrets_key_file:
        raise ValueError("Server encryption key is not configured")
    key = base64.b64decode(read_secret(cfg.secrets_key_file), validate=True)
    if len(key) != 32:
        raise ValueError("Invalid server encryption key")
    return AESGCM(key)


def encrypt(cfg: Settings, provider_id: str, secret: str) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(
        nonce + cipher(cfg).encrypt(nonce, secret.encode(), provider_id.encode())
    ).decode()


def decrypt(cfg: Settings, provider_id: str, encrypted: str) -> str:
    blob = base64.b64decode(encrypted, validate=True)
    return cipher(cfg).decrypt(blob[:12], blob[12:], provider_id.encode()).decode()


def seed(db: Session, cfg: Settings) -> None:
    # Runtime bootstrap is metadata only; original server secret files stay untouched.
    for kind in ("local", "openrouter"):
        provider_id = kind + "-default"
        if db.get(ProviderConfig, provider_id):
            continue
        payload = ProviderInput(
            name="Lokales Modell" if kind == "local" else "OpenRouter",
            kind=kind,
            base_url=cfg.local_base_url if kind == "local" else "https://openrouter.ai/v1",
            model=cfg.local_model if kind == "local" else cfg.openrouter_model,
            capabilities=["text", "structured"] if kind == "local" else ["text"],
            allowed_labels=["LOCAL_ONLY", "CLOUD_ALLOWED"]
            if kind == "local"
            else ["CLOUD_ALLOWED"],
            is_default=True,
            disable_thinking=cfg.local_disable_thinking if kind == "local" else False,
        )
        row = ProviderConfig(
            id=provider_id,
            name=payload.name,
            kind=kind,
            revision=1,
            enabled=True,
            is_default=True,
            config=json.dumps(payload.model_dump(exclude={"api_key", "revision", "clear_secret"})),
        )
        db.add(row)
        db.add(ProviderRevision(provider_id=provider_id, revision=1, config=row.config))
    db.flush()


def public(row: ProviderConfig, cfg: Settings) -> dict[str, object]:
    data: dict[str, object] = json.loads(row.config)
    data.update(
        id=row.id,
        name=row.name,
        kind=row.kind,
        revision=row.revision,
        enabled=row.enabled,
        is_default=row.is_default,
    )
    server_secret = bool(data.get("use_server_secret", True)) and (
        (row.id == "local-default" and bool(cfg.local_key_file))
        or (row.id == "openrouter-default" and bool(cfg.openrouter_key_file))
    )
    data["secret_ref"] = (
        "encrypted" if row.encrypted_secret else "server" if server_secret else None
    )
    return data


def runtime_provider(
    factory: sessionmaker[Session], cfg: Settings
) -> tuple[Settings, Providers, dict[str, ProviderConfig]]:
    with factory() as db:
        seed(db, cfg)
        rows = list(db.scalars(select(ProviderConfig).where(ProviderConfig.is_default.is_(True))))
        db.commit()
    selected = {r.kind: r for r in rows}
    values: dict[str, object] = {}
    keys: dict[str, str] = {}
    for kind in ("local", "openrouter"):
        row = selected.get(kind)
        if not row or not row.enabled:
            values[kind + "_model"] = ""
            continue
        data = json.loads(row.config)
        values[kind + "_model"] = data["model"]
        values[kind + "_timeout"] = data["timeout"]
        values[kind + "_max_tokens"] = data["output_tokens"]
        if kind == "local":
            if data["base_url"] not in local_endpoints(cfg):
                raise ValueError("Local endpoint is not allowed")
            values["local_base_url"] = data["base_url"]
            values["local_allowed_ip"] = local_endpoints(cfg)[data["base_url"]]
            values["local_allowed_labels"] = tuple(data["allowed_labels"])
            values["local_disable_thinking"] = data["disable_thinking"]
            values["context_limit"] = data["context_chars"]
        if row.encrypted_secret:
            keys[kind] = decrypt(cfg, row.id, row.encrypted_secret)
        elif row.id != kind + "-default" or not data.get("use_server_secret", True):
            values[kind + "_key_file"] = ""
    settings = replace(cfg, **values)  # type: ignore[arg-type]
    return settings, Providers(settings, keys=keys), selected


async def fresh_cloud_prices(
    factory: sessionmaker[Session], row: ProviderConfig, provider: Providers
) -> ProviderConfig:
    """Refresh public metadata on demand; never send conversation content."""
    data = json.loads(row.config)
    pricing = data.get("pricing")
    if pricing and time.time() - pricing["verified_at"] <= 3600:
        return row
    if not row.enabled or row.kind != "openrouter":
        raise ExecutionLimitError("Cloudprovider deaktiviert")
    catalog = await provider.models(external=True)
    selected = next((m for m in catalog if m["id"] == data["model"]), None)
    if not selected or not isinstance(selected.get("pricing"), dict):
        raise ExecutionLimitError("Modellpreise nicht verfügbar; kein Cloudaufruf")
    rates = selected["pricing"]
    assert isinstance(rates, dict)
    prompt, completion = Decimal(str(rates["prompt"])), Decimal(str(rates["completion"]))
    if not prompt.is_finite() or not completion.is_finite() or min(prompt, completion) < 0:
        raise ExecutionLimitError("Ungültige Modellpreise; kein Cloudaufruf")
    context = selected.get("context_length")
    if context is not None and (
        not isinstance(context, int) or isinstance(context, bool) or context <= 0
    ):
        raise ExecutionLimitError("Ungültige Modellmetadaten; kein Cloudaufruf")
    with factory() as db:
        current = db.scalar(
            select(ProviderConfig).where(ProviderConfig.id == row.id).with_for_update()
        )
        if not current or not current.enabled or current.revision != row.revision:
            raise ExecutionLimitError("Provider während Preisprüfung geändert")
        data["pricing"] = {
            "input": str(prompt),
            "output": str(completion),
            "verified_at": time.time(),
            "context_tokens": context,
        }
        current.config = json.dumps(data)
        current.revision += 1
        db.add(
            ProviderRevision(
                provider_id=current.id, revision=current.revision, config=current.config
            )
        )
        db.commit()
        return current
