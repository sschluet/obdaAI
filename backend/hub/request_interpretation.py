"""Bounded local semantic interpretation. It grants no target or execution rights."""

import asyncio
import json
import time
from dataclasses import replace
from typing import Any

from hub.agent_intent import accept_semantic, semantic_failure_feedback, semantic_request
from hub.db import Conversation, ProviderConfig, Run
from hub.db_locks import ownership_lock
from hub.inference_capacity import InferenceWaitTimeout
from hub.policy import ContextPart
from hub.provider_settings import runtime_provider


async def interpret(
    factory: Any,
    cfg: Any,
    goal: str,
    profiles: dict[str, Any],
    *,
    prior_target_ids: list[str] | None = None,
    conversation_id: str | None = None,
) -> Any:
    request = semantic_request(goal, profiles, prior_target_ids=prior_target_ids or [])
    settings, provider, selected = runtime_provider(factory, cfg, local_only=True)
    if not selected.get("local") or not settings.local_model:
        raise ValueError("Local interpretation is not available")
    provider.settings = replace(
        settings, local_max_tokens=min(settings.local_max_tokens, 768), local_disable_thinking=True
    )
    provider.local_json_schema = request["schema"]
    selected_local = selected["local"]

    def before_send() -> None:
        with factory() as db:
            current = db.get(ProviderConfig, selected_local.id)
            active = db.get(Run, run_id)
            owner = db.get(Conversation, conversation_id) if conversation_id else None
            if conversation_id and (not owner or owner.archived or owner.purpose != "chat"):
                raise PermissionError("Interpreter source conversation changed while waiting")
            if (
                not current
                or not current.enabled
                or not current.is_default
                or current.revision != selected_local.revision
                or not active
                or active.cancel_requested
                or active.status != "streaming"
            ):
                raise PermissionError("Local interpreter changed while waiting")

    provider.before_send = before_send
    parts = [
        ContextPart(content=request["instruction"], source_id="intent-policy", revision=1),
        ContextPart(
            content=json.dumps(request["data"], ensure_ascii=False),
            source_id="intent-request",
            revision=1,
        ),
    ]
    limits = json.loads(selected_local.config)
    if (
        sum(len(part.content) for part in parts) > limits["context_chars"]
        or sum(len(part.content.encode()) + 64 for part in parts)
        + 4096
        + provider.settings.local_max_tokens
        > limits["context_tokens"]
    ):
        raise ValueError("Intent context exceeds the configured local model boundary")
    with factory() as db:
        ownership_lock(db)
        owner = db.get(Conversation, conversation_id) if conversation_id else None
        if conversation_id and (not owner or owner.archived or owner.purpose != "chat"):
            raise PermissionError("Interpreter source conversation is unavailable")
        conversation = Conversation(
            purpose="intent", title="Auftrag einordnen", manual_title=True, cloud_allowed=False
        )
        db.add(conversation)
        db.flush()
        run = Run(
            conversation_id=conversation.id,
            status="streaming",
            provider="local",
            model=settings.local_model,
            provider_revision=selected_local.revision,
            answer_model_used=True,
            started=time.time(),
            context_snapshot=json.dumps(
                {
                    "parts": [p.model_dump(mode="json") for p in parts],
                    "roles": ["system", "user"],
                    "model_local_only": True,
                    "interpretation": True,
                    "request_owner": conversation_id,
                },
                ensure_ascii=False,
            ),
        )
        db.add(run)
        db.flush()
        run_id, hidden_conversation_id = run.id, conversation.id
        db.commit()
    success = False
    interrupted = False
    accepted: dict[str, Any] | None = None
    started = time.monotonic()
    first_content: float | None = None
    ready_at: float | None = None
    phase_times: dict[str, float] = {}
    timeout_phase: str | None = None

    def progress(phase: str) -> None:
        nonlocal ready_at
        if phase == "model_ready" and ready_at is None:
            ready_at = time.monotonic()
            phase_times["queue_seconds"] = round(ready_at - started, 3)

    provider.on_progress = progress
    attempts: list[dict[str, Any]] = []
    try:
        # Both interpretations share one deadline and the same final provider/owner gates.
        async with asyncio.timeout(min(cfg.generation_timeout, 120)):
            for attempt in range(2):
                chunks = []
                async for chunk in provider.stream(
                    parts, ["system", "user"], external=False, grants=[]
                ):
                    if chunk and first_content is None:
                        first_content = time.monotonic() - started
                        if ready_at is not None:
                            phase_times["prefill_seconds"] = round(time.monotonic() - ready_at, 3)
                    chunks.append(chunk)
                    if sum(len(item) for item in chunks) > 12000:
                        raise ValueError("Intent output exceeded its bound")
                try:
                    result = accept_semantic(json.loads("".join(chunks)), profiles, goal=goal)
                except ValueError as error:
                    feedback = semantic_failure_feedback(error)
                    issue = feedback["semantic_feedback"]["issue"]
                    attempts.append({"status": "invalid", "issue": issue})
                    if attempt:
                        raise
                    corrected = [
                        *parts[:1],
                        parts[1].model_copy(
                            update={
                                "content": json.dumps(
                                    {**request["data"], **feedback}, ensure_ascii=False
                                ),
                            }
                        ),
                    ]
                    if (
                        sum(len(part.content) for part in corrected) > limits["context_chars"]
                        or sum(len(part.content.encode()) + 64 for part in corrected)
                        + 4096
                        + provider.settings.local_max_tokens
                        > limits["context_tokens"]
                    ):
                        raise ValueError("Intent repair exceeds the local model boundary") from None
                    parts = corrected
                    continue
                attempts.append({"status": "succeeded"})
                accepted = result.model_dump(mode="json")
                success = True
                return result
    except InferenceWaitTimeout as error:
        timeout_phase = error.phase
        raise
    except asyncio.CancelledError:
        interrupted = True
        raise
    finally:
        with factory() as db:
            run = db.get(Run, run_id)
            conversation = db.get(Conversation, hidden_conversation_id)
            assert run and conversation
            run.status = (
                "succeeded"
                if success
                else "cancelled"
                if interrupted or run.cancel_requested
                else "failed"
            )
            run.finished = time.time()
            run.first_content_seconds = first_content
            run.routing_trace = json.dumps(
                {
                    "intent": accepted,
                    "interpretation_seconds": round(time.monotonic() - started, 3),
                    "inference_phases": phase_times,
                    "semantic_attempts": attempts,
                    **({"inference_timeout_phase": timeout_phase} if timeout_phase else {}),
                },
                ensure_ascii=False,
            )
            run.error = "" if success else "Lokale Auftragseinordnung nicht abgeschlossen"
            conversation.archived = True
            db.commit()
