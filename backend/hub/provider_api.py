"""Authenticated settings, metadata connection tests and queued inference probes."""

import asyncio
import json
import time
from dataclasses import replace
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from hub.auth import require_session
from hub.budgets import month, reserve, settle
from hub.config import Settings
from hub.db import (
    BudgetReservation,
    LoginSession,
    ProviderConfig,
    ProviderRevision,
    ProviderTest,
    new_id,
)
from hub.policy import CloudGrant, ContextPart, Privacy
from hub.provider_settings import (
    ProviderInput,
    decrypt,
    encrypt,
    local_endpoints,
    public,
    seed,
    validate_endpoint,
)
from hub.providers import Providers

Authenticated = Annotated[LoginSession, Depends(require_session)]


class ProbeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    mode: str = Field(pattern="^(connection|model)$")


def adapter(row: ProviderConfig, cfg: Settings) -> Providers:
    data = json.loads(row.config)
    external = row.kind == "openrouter"
    if not row.enabled or (external and not cfg.cloud_enabled):
        raise PermissionError("Provider disabled by server policy")
    body = ProviderInput.model_validate(
        {k: v for k, v in data.items() if k not in ("pricing", "use_server_secret")}
    )
    validate_endpoint(body, cfg)
    keys = {row.kind: decrypt(cfg, row.id, row.encrypted_secret)} if row.encrypted_secret else {}
    local_file = (
        cfg.local_key_file
        if row.id == "local-default" and data.get("use_server_secret", True)
        else ""
    )
    cloud_file = (
        cfg.openrouter_key_file
        if row.id == "openrouter-default" and data.get("use_server_secret", True)
        else ""
    )
    settings = replace(
        cfg,
        local_base_url=data["base_url"] if not external else cfg.local_base_url,
        local_allowed_ip=local_endpoints(cfg).get(data["base_url"], cfg.local_allowed_ip),
        local_allowed_labels=tuple(data["allowed_labels"])
        if not external
        else cfg.local_allowed_labels,
        local_model=data["model"] if not external else cfg.local_model,
        openrouter_model=data["model"] if external else cfg.openrouter_model,
        local_key_file=local_file,
        openrouter_key_file=cloud_file,
        local_timeout=data["timeout"],
        openrouter_timeout=data["timeout"],
        local_max_tokens=min(data["output_tokens"], 128),
        openrouter_max_tokens=min(data["output_tokens"], 128),
        local_disable_thinking=data["disable_thinking"],
    )
    return Providers(settings, keys=keys)


async def execute_probe(factory: sessionmaker[Session], cfg: Settings, test_id: str) -> None:
    with factory() as db:
        test = db.scalar(select(ProviderTest).where(ProviderTest.id == test_id).with_for_update())
        if not test or test.status != "queued":
            if test and test.status == "running":
                test.status, test.result = (
                    "interrupted",
                    "Modelltest unterbrochen; nicht wiederholt",
                )
                db.commit()
            return
        test.status = "running"
        db.commit()
        row = db.get(ProviderConfig, test.provider_id)
        if not row or row.revision != test.revision:
            test.status, test.result = "failed", "Provider geändert; Modelltest erneut starten"
            db.commit()
            return
    result, state, measured = "Modelltest fehlgeschlagen; kein Fallback", "failed", None
    try:
        p = adapter(row, cfg)
        external = row.kind == "openrouter"
        part = ContextPart(
            content="What is 2 plus 2? Answer with the number only.",
            label=Privacy.CLOUD_ALLOWED if external else Privacy.LOCAL_ONLY,
            source_id=test_id,
            revision=1,
        )
        started = time.monotonic()
        async with asyncio.timeout(60):
            if external:
                with factory() as db:
                    reserve(db, row, test_id, [part])
                    db.commit()
                text = "".join(
                    [
                        chunk
                        async for chunk in p.stream(
                            [part],
                            ["user"],
                            external=True,
                            grants=[
                                CloudGrant(source_id=test_id, revision=1, provider_id="openrouter")
                            ],
                        )
                    ]
                )
                measured = p.measured_cost
            else:
                decision = await p.route([part], ["user"])
                text = decision.answer or ""
            if text.strip() != "4":
                raise ValueError("Synthetic model check failed")
            result, state = (
                f"Modelltest bestanden · {time.monotonic() - started:.2f} s",
                "succeeded",
            )
    except asyncio.CancelledError:
        result, state = "Modelltest unterbrochen", "interrupted"
        raise
    except Exception:
        pass
    finally:
        with factory() as db:
            test = db.get(ProviderTest, test_id)
            if test:
                test.status, test.result = state, result
            settle(db, test_id, measured)
            db.commit()


def install_provider_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    @app.get("/api/providers")
    def list_providers(session: Authenticated) -> dict[str, object]:
        with factory() as db:
            seed(db, cfg)
            db.commit()
            rows = list(db.scalars(select(ProviderConfig).order_by(ProviderConfig.name)))
            used = {
                r.id: db.scalar(
                    select(
                        func.coalesce(
                            func.sum(
                                func.coalesce(BudgetReservation.measured, BudgetReservation.ceiling)
                            ),
                            0,
                        )
                    ).where(
                        BudgetReservation.provider_id == r.id, BudgetReservation.month == month()
                    )
                )
                for r in rows
            }
            tests: dict[str, dict[str, str] | None] = {}
            for row in rows:
                probe = db.scalar(
                    select(ProviderTest)
                    .where(ProviderTest.provider_id == row.id)
                    .order_by(ProviderTest.created.desc())
                    .limit(1)
                )
                tests[row.id] = {"status": probe.status, "result": probe.result} if probe else None
            return {
                "providers": [
                    dict(
                        public(r, cfg),
                        budget_used=used[r.id],
                        last_test=tests[r.id],
                    )
                    for r in rows
                ],
                "local_endpoints": list(local_endpoints(cfg)),
                "cloud_enabled": cfg.cloud_enabled,
                "encrypted_secrets_available": bool(cfg.secrets_key_file),
            }

    @app.post("/api/providers")
    def create_provider(body: ProviderInput, session: Authenticated) -> dict[str, object]:
        return save(new_id(), body, creating=True)

    @app.put("/api/providers/{provider_id}")
    def update_provider(
        provider_id: str, body: ProviderInput, session: Authenticated
    ) -> dict[str, object]:
        return save(provider_id, body, creating=False)

    def save(provider_id: str, body: ProviderInput, *, creating: bool) -> dict[str, object]:
        try:
            validate_endpoint(body, cfg)
            with factory() as db:
                seed(db, cfg)
                row = db.scalar(
                    select(ProviderConfig).where(ProviderConfig.id == provider_id).with_for_update()
                )
                if creating:
                    row = ProviderConfig(
                        id=provider_id,
                        revision=0,
                        name=body.name,
                        kind=body.kind,
                        config="{}",
                        is_default=False,
                    )
                    db.add(row)
                elif not row:
                    raise HTTPException(404, "Provider nicht gefunden")
                assert row is not None
                if not creating and (body.revision != row.revision or body.kind != row.kind):
                    raise HTTPException(409, "Provider wurde geändert; neu laden")
                old = json.loads(row.config) if row.config else {}
                data = body.model_dump(exclude={"api_key", "revision", "clear_secret"})
                data["use_server_secret"] = old.get(
                    "use_server_secret", provider_id in ("local-default", "openrouter-default")
                )
                if body.api_key:
                    row.encrypted_secret = encrypt(cfg, provider_id, body.api_key)
                    data["use_server_secret"] = False
                if body.clear_secret:
                    row.encrypted_secret = None
                    data["use_server_secret"] = False
                if old.get("model") == body.model and old.get("pricing"):
                    data["pricing"] = old["pricing"]
                if body.is_default:
                    for other in db.scalars(
                        select(ProviderConfig).where(
                            ProviderConfig.kind == body.kind, ProviderConfig.id != provider_id
                        )
                    ):
                        if other.is_default:
                            other.is_default = False
                            other.revision += 1
                            old_data = json.loads(other.config)
                            old_data["is_default"] = False
                            other.config = json.dumps(old_data)
                            db.add(
                                ProviderRevision(
                                    provider_id=other.id,
                                    revision=other.revision,
                                    config=other.config,
                                )
                            )
                db.flush()
                row.name, row.kind, row.enabled, row.is_default = (
                    body.name,
                    body.kind,
                    body.enabled,
                    body.is_default,
                )
                row.revision += 1
                row.config = json.dumps(data)
                db.add(
                    ProviderRevision(provider_id=row.id, revision=row.revision, config=row.config)
                )
                db.commit()
                return public(row, cfg)
        except ValueError:
            raise HTTPException(
                422, "Providerdaten, erlaubtes Netzwerkziel oder Verschlüsselung prüfen"
            ) from None

    @app.get("/api/providers/{provider_id}/revisions")
    def revisions(provider_id: str, session: Authenticated) -> list[dict[str, object]]:
        with factory() as db:
            return [
                {"revision": r.revision, "created": r.created, "config": json.loads(r.config)}
                for r in db.scalars(
                    select(ProviderRevision)
                    .where(ProviderRevision.provider_id == provider_id)
                    .order_by(ProviderRevision.revision.desc())
                )
            ]

    @app.post("/api/providers/{provider_id}/test")
    async def test_provider(
        provider_id: str, body: ProbeInput, session: Authenticated
    ) -> dict[str, object]:
        with factory() as db:
            row = db.get(ProviderConfig, provider_id)
            if not row:
                raise HTTPException(404, "Provider nicht gefunden")
            if not row.enabled or (row.kind == "openrouter" and not cfg.cloud_enabled):
                raise HTTPException(409, "Provider deaktiviert oder Cloud am Server gesperrt")
            if body.mode == "model":
                if not body.request_id:
                    raise HTTPException(422, "Modelltest benötigt eine eindeutige Anfrage-ID")
                previous = db.get(ProviderTest, body.request_id)
                if previous:
                    if previous.provider_id != row.id:
                        raise HTTPException(409, "Anfrage-ID gehört zu anderem Provider")
                    return {"id": previous.id, "status": previous.status}
                probe = ProviderTest(id=body.request_id, provider_id=row.id, revision=row.revision)
                db.add(probe)
                db.flush()
                if not cfg.database_url.startswith("sqlite"):
                    from hub.jobs import enqueue_probe

                    enqueue_probe(db, cfg, probe.id)
                db.commit()
                if cfg.database_url.startswith("sqlite"):
                    task = asyncio.create_task(execute_probe(factory, cfg, probe.id))
                    app.state.tasks.add(task)
                    task.add_done_callback(app.state.tasks.discard)
                return {"id": probe.id, "status": "queued"}
            revision = row.revision
        try:
            catalog = await adapter(row, cfg).models(external=row.kind == "openrouter")
            data = json.loads(row.config)
            selected = next((m for m in catalog if m["id"] == data["model"]), None)
            if not selected:
                return {
                    "status": "succeeded",
                    "model_found": False,
                    "message": "Verbindung hergestellt; konfiguriertes Modell fehlt im Katalog",
                    "models": [m["id"] for m in catalog][:200],
                }
            if row.kind == "openrouter":
                rates = selected["pricing"]
                assert isinstance(rates, dict)
                prompt, completion = (
                    Decimal(str(rates["prompt"])),
                    Decimal(str(rates["completion"])),
                )
                if (
                    not prompt.is_finite()
                    or not completion.is_finite()
                    or min(prompt, completion) < 0
                ):
                    raise ValueError("Invalid model rates")
                data["pricing"] = {
                    "input": str(prompt),
                    "output": str(completion),
                    "verified_at": time.time(),
                    "context_tokens": selected.get("context_length"),
                }
                with factory() as db:
                    current = db.scalar(
                        select(ProviderConfig).where(ProviderConfig.id == row.id).with_for_update()
                    )
                    if current is None or current.revision != revision:
                        raise HTTPException(409, "Provider geändert; Verbindungstest wiederholen")
                    current.config = json.dumps(data)
                    current.revision += 1
                    db.add(
                        ProviderRevision(
                            provider_id=current.id, revision=current.revision, config=current.config
                        )
                    )
                    db.commit()
            return {
                "status": "succeeded",
                "message": "Verbindung und konfiguriertes Modell gefunden",
                "models": [m["id"] for m in catalog][:200],
            }
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                503, "Verbindung oder Modellkatalog nicht verfügbar; kein Fallback"
            ) from None

    @app.get("/api/provider-tests/{test_id}")
    def get_test(test_id: str, session: Authenticated) -> dict[str, object]:
        with factory() as db:
            test = db.get(ProviderTest, test_id)
            if not test:
                raise HTTPException(404, "Modelltest nicht gefunden")
            return {"id": test.id, "status": test.status, "result": test.result}
