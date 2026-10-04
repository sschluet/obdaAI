"""Chat execution independent of HTTP; one worker owns each queued run."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Protocol

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.orm import Session, sessionmaker

from hub.budgets import ExecutionLimitError, reserve, settle
from hub.config import Settings
from hub.db import Conversation, Message, ProviderConfig, Run, RunEvent
from hub.policy import CloudGrant, ContextPart, Privacy
from hub.provider_settings import runtime_provider
from hub.providers import Providers
from hub.routing import Capability, Route
from hub.titles import execute_title, reserve_title


class ChatProvider(Protocol):
    async def title(self, parts: list[ContextPart], roles: list[str]) -> str: ...
    async def route(self, parts: list[ContextPart], roles: list[str]) -> Route: ...
    def stream(
        self,
        parts: list[ContextPart],
        roles: list[str],
        *,
        external: bool,
        grants: list[CloudGrant],
    ) -> AsyncIterator[str]: ...


async def execute_run(
    factory: sessionmaker[Session], cfg: Settings, providers: ChatProvider, run_id: str
) -> None:
    with factory() as db:
        claimed = db.scalar(
            sql_update(Run)
            .where(Run.id == run_id, Run.status == "queued")
            .values(status="routing")
            .returning(Run.id)
        )
        db.commit()
        if claimed is None:
            return  # No automatic repeat of a paid or partial model call.
        run = db.get(Run, run_id)
        assert run is not None
        chat_id = run.conversation_id
        c = db.get(Conversation, chat_id)
        assert c is not None
        messages = db.scalars(
            select(Message)
            .where(Message.conversation_id == chat_id, Message.active.is_(True))
            .order_by(Message.created, Message.id)
        ).all()
        parts = [
            ContextPart(
                content=m.content, label=Privacy(m.label), source_id=m.id, revision=m.revision
            )
            for m in messages
        ]
        roles = [m.role for m in messages]
        if run.context_snapshot:
            snapshot = json.loads(run.context_snapshot)
            parts = [ContextPart.model_validate(p) for p in snapshot["parts"]]
            roles = snapshot["roles"]
        label = (
            Privacy.LOCAL_ONLY
            if any(p.label == Privacy.LOCAL_ONLY for p in parts)
            else Privacy.CLOUD_ALLOWED
        )
        grants = (
            [
                CloudGrant(source_id=p.source_id, revision=p.revision, provider_id="openrouter")
                for p in parts
            ]
            if c.cloud_allowed
            else []
        )

    def update(**values: object) -> None:
        with factory() as db:
            current = db.get(Run, run_id)
            if current:
                for key, value in values.items():
                    setattr(current, key, value)
                db.commit()

    def cancelled() -> bool:
        with factory() as db:
            current = db.get(Run, run_id)
            return bool(current and current.cancel_requested)

    async def generate() -> AsyncIterator[tuple[str, object]]:
        nonlocal cfg, providers
        output = ""
        status = "failed"
        reserved = False
        started = time.monotonic()
        yield ("run", {"id": run_id})
        yield ("status", {"message": "Anfrage wird lokal eingeordnet"})
        try:
            selected: dict[str, ProviderConfig] = {}
            if isinstance(providers, Providers):
                cfg, providers, selected = runtime_provider(factory, cfg)
                local = selected.get("local")
                if not local or not local.enabled:
                    raise ExecutionLimitError("Lokaler Router ist deaktiviert")
                limits = json.loads(local.config)
                if not {"text", "structured"}.issubset(limits["capabilities"]):
                    raise ExecutionLimitError(
                        "Lokaler Router benötigt Text und strukturierte Ausgabe"
                    )
                input_bound = sum(len(p.content.encode()) + 64 for p in parts) + 4096
                if (
                    sum(len(p.content) for p in parts) > limits["context_chars"]
                    or input_bound + min(1024, limits["output_tokens"]) > limits["context_tokens"]
                ):
                    raise ExecutionLimitError("Kontextgrenze des lokalen Modells erreicht")
                if any(p.label not in limits["allowed_labels"] for p in parts):
                    raise PermissionError("Local model privacy class not allowed")
            async with asyncio.timeout(cfg.run_timeout):
                if cancelled():
                    raise asyncio.CancelledError
                route = await providers.route(parts, roles)
                update(
                    router_seconds=time.monotonic() - started,
                    reason=route.reason,
                    capabilities=json.dumps([str(c) for c in route.capabilities]),
                )
                if cancelled():
                    raise asyncio.CancelledError
                unsupported = set(route.capabilities) - {Capability.CHAT}
                if unsupported:
                    raise NotImplementedError
                external = route.model_class == "cloud"
                if external and (
                    not cfg.cloud_enabled or any(p.label == Privacy.LOCAL_ONLY for p in parts)
                ):
                    # Complex requests can still be answered locally. This is a
                    # policy choice, not an external provider outage fallback.
                    external = False
                    yield ("status", {"message": "Datenschutzregel hält diese Antwort lokal"})
                provider = "openrouter" if external else "local"
                if external and selected:
                    cloud = selected.get("openrouter")
                    if cloud is None:
                        raise ValueError("Cloud provider not configured")
                    with factory() as db:
                        estimate = reserve(db, cloud, run_id, parts)
                        current = db.get(Run, run_id)
                        assert current is not None
                        current.cost_estimate = estimate
                        db.commit()
                    reserved = True
                selected_provider = selected.get(provider)
                update(
                    status="streaming",
                    provider=provider,
                    model=cfg.openrouter_model if external else cfg.local_model,
                    provider_revision=selected_provider.revision if selected_provider else None,
                )
                yield ("provider", {"name": provider, "reason": route.reason})
                if route.answer:
                    output = route.answer
                    update(first_content_seconds=time.monotonic() - started)
                    yield ("delta", {"text": output})
                else:
                    async for chunk in providers.stream(
                        parts, roles, external=external, grants=grants
                    ):
                        if cancelled():
                            raise asyncio.CancelledError
                        if not output:
                            update(first_content_seconds=time.monotonic() - started)
                        output += chunk
                        if len(output) > 32000:
                            raise ValueError("Output limit exceeded")
                        yield ("delta", {"text": chunk})
                if not output:
                    raise ValueError("Empty provider response")
                status = "succeeded"
        except asyncio.CancelledError:
            status = "cancelled" if cancelled() else "interrupted"
        except NotImplementedError:
            update(error="Benötigte Werkzeuge sind in diesem Meilenstein noch nicht verfügbar")
            yield (
                "error",
                {
                    "message": "Diese Anfrage benötigt Funktionen aus M2–M4. "
                    "Es wurde kein Werkzeug ausgeführt."
                },
            )
        except ExecutionLimitError as error:
            update(error=str(error))
            yield ("error", {"message": str(error)})
        except Exception:
            update(error="Provider nicht verfügbar oder ungültige Antwort")
            yield (
                "error",
                {
                    "message": "Antwort fehlgeschlagen. Lokalen Dienst und Provider prüfen; "
                    "kein Cloud-Fallback."
                },
            )
        finally:
            with factory() as db:
                if output:
                    db.add(
                        Message(
                            conversation_id=chat_id,
                            role="assistant",
                            content=output,
                            label=label,
                        )
                    )
                current = db.get(Run, run_id)
                if current:
                    current.status, current.finished = status, time.time()
                if reserved and isinstance(providers, Providers):
                    settle(db, run_id, providers.measured_cost)
                    if current:
                        current.cost = providers.measured_cost
                if status == "succeeded":
                    reserve_title(db, cfg, chat_id)
                db.commit()
        yield ("done", {"status": status})

    async def persist() -> None:
        sequence = 0
        async for kind, value in generate():
            sequence += 1
            with factory() as db:
                db.add(
                    RunEvent(
                        run_id=run_id,
                        sequence=sequence,
                        kind=kind,
                        payload=json.dumps(value, ensure_ascii=False),
                    )
                )
                db.commit()

    task = asyncio.create_task(persist())
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.2)
            if cancelled() and not task.done():
                task.cancel()
        await task
        if cfg.database_url.startswith("sqlite"):
            await execute_title(factory, providers, chat_id)
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
