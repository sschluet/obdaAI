"""Authenticated settings, metadata connection tests and queued inference probes."""

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import Annotated, Any

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
from hub.provider_account import install_account_api
from hub.provider_settings import (
    ProviderInput,
    decrypt,
    encrypt,
    fresh_cloud_prices,
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
    mode: str = Field(pattern="^(connection|model|planner)$")


def adapter(row: ProviderConfig, cfg: Settings) -> Providers:
    data = json.loads(row.config)
    external = row.kind != "local"
    if not row.enabled or (
        external and (not cfg.cloud_enabled or row.kind not in cfg.external_provider_kinds)
    ):
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
    return Providers(settings, keys=keys, external_kind=row.kind if external else "openrouter")


def _planner_result(message: str, provenance: dict[str, Any]) -> str:
    return json.dumps(
        {"planner_probe_version": 1, "message": message, "provenance": provenance},
        ensure_ascii=False,
    )


def _probe_result(test: ProviderTest) -> dict[str, Any]:
    if test.mode == "planner":
        try:
            value = json.loads(test.result or "")
            if value.get("planner_probe_version") == 1:
                return {"result": value["message"], "provenance": value["provenance"]}
        except (ValueError, TypeError, AttributeError, KeyError):
            pass
    return {"result": test.result}


async def _execute_planner_probe(
    factory: sessionmaker[Session],
    cfg: Settings,
    row: ProviderConfig,
    p: Providers,
    test_id: str,
    current_permission: Callable[[], None],
    provenance: dict[str, Any],
) -> None:
    from hub.agent_capabilities import describe
    from hub.agent_context import AgentContextLimitError, fit
    from hub.agent_instructions import instruction
    from hub.agent_intent import accept_semantic, semantic_request
    from hub.agent_native import (
        NATIVE_NO_SELECTION,
        NativeProtocolUnavailable,
        auxiliary_parts,
        metadata_size,
        prepare,
    )
    from hub.agent_tools import Rules, decision_schema, validate_tool
    from hub.integrations import Integration

    limits = json.loads(row.config)
    p.settings = replace(
        p.settings, local_max_tokens=min(768, limits["output_tokens"]), local_disable_thinking=True
    )
    profile = Integration(
        id="synthetic-ha",
        name="Synthetic Home Assistant",
        kind="home_assistant",
        config="{}",
        enabled=True,
    )
    profiles: dict[str, Any] = {profile.id: (profile, None, {})}

    def progress(protocol: str) -> dict[str, Any]:
        current_permission()
        attempt = {"protocol": protocol, "status": "running"}
        provenance["attempts"].append(attempt)
        save_progress()
        return attempt

    def save_progress() -> None:
        with factory() as db:
            test = db.get(ProviderTest, test_id)
            if not test or test.status != "running":
                raise asyncio.CancelledError
            test.result = _planner_result("Planertest läuft", provenance)
            db.commit()

    def parts_for(
        policy: str, data: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> list[ContextPart]:
        auxiliary = auxiliary_parts(metadata) if metadata is not None else []
        chars, encoded = metadata_size(metadata) if metadata is not None else (0, 0)
        # Conservative byte-per-token bound includes the transport envelopes,
        # output allowance and every auxiliary native tool-schema byte.
        available = (
            limits["context_tokens"]
            - 4096
            - 64 * (2 + len(auxiliary))
            - p.settings.local_max_tokens
            - encoded
        )
        limit = min(cfg.context_limit, limits["context_chars"]) - chars
        if min(available, limit) <= 0:
            raise AgentContextLimitError("Probe context does not fit")
        fitted = fit(data, policy, limit, max_bytes=available)
        parts = [
            ContextPart(
                content=policy, label=Privacy.LOCAL_ONLY, source_id=test_id + ":policy", revision=1
            ),
            ContextPart(
                content=json.dumps(fitted, ensure_ascii=False),
                label=Privacy.LOCAL_ONLY,
                source_id=test_id + ":data",
                revision=1,
            ),
        ]
        if (
            sum(len(part.content) for part in parts) > limit
            or sum(len(part.content.encode()) for part in parts) > available
        ):
            raise AgentContextLimitError("Serialized probe context does not fit")
        return parts

    async def infer(parts: list[ContextPart]) -> Any:
        text = "".join(
            [
                chunk
                async for chunk in p.stream(parts, ["system", "user"], external=False, grants=[])
            ]
        )
        return json.loads(text)

    request = semantic_request("Welche Lampen gibt es in Home Assistant?", profiles)
    intent_attempt = progress("json_intent")
    p.local_native_plan, p.local_json_schema = None, request["schema"]
    accepted = accept_semantic(
        await infer(parts_for(request["instruction"], request["data"])), profiles
    )
    if (
        accepted.mode != "observe"
        or accepted.target_ids != [profile.id]
        or not any(r.kind == "entity_states" and r.domain == "light" for r in accepted.requirements)
    ):
        raise ValueError("Synthetic intent check failed")
    provenance["intent_pass"], intent_attempt["status"] = True, "succeeded"
    rules = Rules(enabled=True, http_prefixes=["/api/"], http_methods=["GET"], max_effects=0)
    data: dict[str, Any] = {
        "goal": "Welche Lampen gibt es in Home Assistant?",
        "observed": {"http_status": 200, "body": {"message": "API running."}},
        "read_only": True,
        "allow_finish": False,
        "allow_ask": False,
        "allow_stop": False,
        "tools": ["http"],
        "interfaces": [
            {
                "integration_id": profile.id,
                "kind": profile.kind,
                "read_only": True,
                "writes_enabled": False,
                "rules": rules.model_dump(),
                "capabilities": describe(profile, rules),
            }
        ],
        "request_contract": accepted.model_dump(),
        "history": [],
    }
    data["decision_schema"] = decision_schema(
        [profile.id],
        ["http"],
        data["interfaces"],
        allow_finish=False,
        allow_ask=False,
        allow_stop=False,
        read_only=True,
    )
    policy = instruction({profile.kind})
    native = prepare(policy, data)

    def validate_selection(value: Any) -> None:
        if (
            not isinstance(value, dict)
            or value.get("kind") != "tool"
            or value.get("integration_id") != profile.id
            or value.get("tool") != "http"
        ):
            raise ValueError("Synthetic native selection failed")
        arguments, effect = validate_tool(profile.kind, rules, "http", value.get("arguments", {}))
        if effect or arguments["method"] != "GET" or arguments["path"] != "/api/states":
            raise ValueError("Synthetic read selection failed")

    attempt = progress("native")
    provenance["selection_protocol"] = "native"
    provenance["native_schema_sha256"] = native.metadata["sha256"]
    p.local_json_schema, p.local_native_plan = None, native.metadata
    native_parts = parts_for(native.instruction, native.data, native.metadata)
    try:
        value = await infer(native_parts)
    except NativeProtocolUnavailable:
        attempt["status"] = "unsupported"
    else:
        if isinstance(value, dict) and value.get("_native_error") == NATIVE_NO_SELECTION:
            attempt["status"] = "no_selection"
        else:
            validate_selection(value)
            attempt["status"], provenance["native_pass"] = "succeeded", True
            save_progress()
            return
    # One completed no-selection or explicitly unsupported protocol can be
    # tested separately. Transport/auth/cancel/invalid-call errors never reach here.
    provenance["compatibility_used"] = True
    provenance["selection_protocol"] = "json_compatibility"
    compatible = progress("json_compatibility")
    p.local_native_plan, p.local_json_schema = None, data["decision_schema"]
    validate_selection(await infer(parts_for(policy, data)))
    compatible["status"], provenance["compatibility_pass"] = "succeeded", True
    save_progress()


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
    planner = test.mode == "planner"
    provenance: dict[str, Any] = {
        "version": 1,
        "intent_protocol": "json_schema",
        "intent_pass": False,
        "selection_protocol": "not_started",
        "native_pass": False,
        "compatibility_pass": False,
        "compatibility_used": False,
        "attempts": [],
    }
    result, state, measured = (
        "Planertest fehlgeschlagen" if planner else "Modelltest fehlgeschlagen; kein Fallback",
        "failed",
        None,
    )
    p: Providers | None = None
    try:
        p = adapter(row, cfg)
        external = row.kind != "local"

        def current_permission() -> None:
            assert row is not None
            with factory() as db:
                current = db.get(ProviderConfig, row.id)
                active = db.get(ProviderTest, test_id)
                if not active or active.status != "running":
                    raise asyncio.CancelledError
                if active.provider_id != row.id or active.revision != row.revision:
                    raise PermissionError("Probe binding changed before inference")
                if not current or not current.enabled or current.revision != row.revision:
                    raise PermissionError("Provider changed while waiting for inference")

        p.before_send = current_permission
        planner = test.mode == "planner"
        if planner and external:
            raise PermissionError("Planner checks must remain local")
        part = ContextPart(
            content="What is 2 plus 2? Answer with the number only.",
            label=Privacy.CLOUD_ALLOWED if external else Privacy.LOCAL_ONLY,
            source_id=test_id,
            revision=1,
        )
        started = time.monotonic()
        async with asyncio.timeout(180 if planner else 60):
            if planner:
                await _execute_planner_probe(
                    factory, cfg, row, p, test_id, current_permission, provenance
                )
            elif external:
                row = await fresh_cloud_prices(factory, row, p)
                with factory() as db:
                    current_test = db.get(ProviderTest, test_id)
                    assert current_test is not None
                    current_test.revision = row.revision
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
                                CloudGrant(source_id=test_id, revision=1, provider_id=row.kind)
                            ],
                        )
                    ]
                )
                measured = p.measured_cost
            else:
                # Exercise both structured routing and actual answer generation.
                # The classifier intentionally never answers the arithmetic prompt.
                await p.route([part], ["user"])
                text = "".join(
                    [chunk async for chunk in p.stream([part], ["user"], external=False, grants=[])]
                )
            if not planner and text.strip() != "4":
                raise ValueError("Synthetic model check failed")
            result, state = (
                f"{'Planertest' if planner else 'Modelltest'} bestanden · "
                + (
                    (
                        "native · "
                        if provenance["native_pass"]
                        else "JSON-Kompatibilität (nativ nicht belegt) · "
                    )
                    if planner
                    else ""
                )
                + f"{time.monotonic() - started:.2f} s"
                + (" · Kosten aus Usage geschätzt" if p.cost_basis == "usage_estimate" else ""),
                "succeeded",
            )
    except asyncio.CancelledError:
        result, state = "Modelltest unterbrochen", "interrupted"
        raise
    except Exception:
        pass
    finally:
        if p is not None:
            p.local_native_plan = None
            p.local_json_schema = None
        if planner:
            for attempt in provenance["attempts"]:
                if attempt["status"] == "running":
                    attempt["status"] = "interrupted" if state == "interrupted" else "failed"
        with factory() as db:
            test = db.get(ProviderTest, test_id)
            if test:
                if test.status in {"interrupted", "cancelled"}:
                    state, result = "interrupted", "Modelltest unterbrochen"
                test.status = state
                test.result = _planner_result(result, provenance) if planner else result
            settle(db, test_id, measured)
            db.commit()


def install_provider_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    install_account_api(app, cfg, factory)

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
            tests: dict[str, dict[str, Any] | None] = {}
            for row in rows:
                probe = db.scalar(
                    select(ProviderTest)
                    .where(ProviderTest.provider_id == row.id)
                    .order_by(ProviderTest.created.desc())
                    .limit(1)
                )
                tests[row.id] = (
                    {
                        "status": probe.status,
                        **_probe_result(probe),
                        "revision": probe.revision,
                        "mode": probe.mode,
                    }
                    if probe
                    else None
                )
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
                "external_provider_kinds": list(cfg.external_provider_kinds),
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
            if not row.enabled or (
                row.kind != "local"
                and (not cfg.cloud_enabled or row.kind not in cfg.external_provider_kinds)
            ):
                raise HTTPException(409, "Provider deaktiviert oder Cloud am Server gesperrt")
            if body.mode in ("model", "planner"):
                if body.mode == "planner" and row.kind != "local":
                    raise HTTPException(422, "Planertest ist ausschließlich lokal verfügbar")
                if not body.request_id:
                    raise HTTPException(422, "Modelltest benötigt eine eindeutige Anfrage-ID")
                previous = db.get(ProviderTest, body.request_id)
                if previous:
                    if previous.provider_id != row.id or previous.mode != body.mode:
                        raise HTTPException(409, "Anfrage-ID gehört zu anderem Provider")
                    return {"id": previous.id, "status": previous.status}
                probe = ProviderTest(
                    id=body.request_id, provider_id=row.id, revision=row.revision, mode=body.mode
                )
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
            catalog = await adapter(row, cfg).models(external=row.kind != "local")
            data = json.loads(row.config)
            selected = next((m for m in catalog if m["id"] == data["model"]), None)
            if not selected:
                return {
                    "status": "succeeded",
                    "model_found": False,
                    "message": "Verbindung hergestellt; konfiguriertes Modell fehlt im Katalog",
                    "models": [m["id"] for m in catalog][:200],
                }
            if row.kind in ("openai", "anthropic"):
                row = await fresh_cloud_prices(factory, row, adapter(row, cfg))
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
            return {"id": test.id, "status": test.status, **_probe_result(test)}
