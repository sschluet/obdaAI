"""Human-authenticated authority and chat entry points for the shared agent loop."""

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import Field
from sqlalchemy import select

from hub.action_api import StrictInput, digest, encode
from hub.agent_models import AgentJob, AgentPolicy, AgentPolicyEvent, AgentStep
from hub.agent_runtime import ACTIVE, complete, create_job, execute_agent, gate, job_info, record
from hub.agent_tools import Rules
from hub.config import Settings
from hub.db import Conversation, Message, Run
from hub.db_locks import ownership_lock
from hub.integration_writes import registry_lock
from hub.integrations import Integration
from hub.knowledge import context as project_context
from hub.knowledge_api import Auth


class PolicyInput(StrictInput):
    expected_revision: int = Field(ge=0)
    expected_profile_revision: int = Field(ge=1)
    rules: Rules


class StartInput(StrictInput):
    request_id: UUID
    goal: str = Field(min_length=1, max_length=8000)
    research_allowed: bool = False
    read_only: bool = False
    reconcile_job_id: UUID | None = None


class ApprovalInput(StrictInput):
    sequence: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReplyInput(ApprovalInput):
    content: str = Field(min_length=1, max_length=8000)


def enqueue_agent(db: Any, cfg: Settings, job_id: str) -> None:
    if cfg.database_url.startswith("sqlite"):
        return
    import procrastinate
    import psycopg

    from hub.jobs import conninfo

    queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo(cfg)))
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, psycopg.Connection):
        raise ValueError("Unexpected database driver")
    raw.execute("SET LOCAL search_path TO hub_queue, public")
    queue.configure_task(name="hub.agent", queue="chat", priority=10, connection=raw).defer(
        job_id=job_id
    )


def start_development_agent(app: FastAPI, cfg: Settings, factory: Any, job_id: str) -> None:
    if cfg.database_url.startswith("sqlite"):
        task = asyncio.create_task(execute_agent(factory, cfg, app.state.providers, job_id))
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)


def install_agent_api(app: FastAPI, cfg: Settings, factory: Any) -> None:
    def checked_gate(db: Any, job: AgentJob, effect: bool = False) -> None:
        try:
            gate(db, cfg, job, effect=effect)
        except (PermissionError, TimeoutError):
            raise HTTPException(
                409, "Auftrag oder Berechtigungen geändert; Lauf neu vorbereiten"
            ) from None

    @app.get("/api/integrations/{integration_id}/agent-policy")
    def policy(integration_id: UUID, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            profile = db.get(Integration, str(integration_id))
            if not profile:
                raise HTTPException(404, "Integration fehlt")
            row = db.get(AgentPolicy, profile.id)
            return {
                "integration_id": profile.id,
                "revision": row.revision if row else 0,
                "profile_revision": profile.revision,
                "writes_enabled": profile.writes_enabled,
                "current": bool(row and row.profile_revision == profile.revision),
                "rules": json.loads(row.rules) if row else Rules().model_dump(),
                "shell_authority": "remote_account_permissions; no directory sandbox",
            }

    @app.put("/api/integrations/{integration_id}/agent-policy")
    def save_policy(integration_id: UUID, body: PolicyInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            registry_lock(db)
            profile = db.get(Integration, str(integration_id))
            row = db.get(AgentPolicy, str(integration_id))
            if (
                not profile
                or profile.revision != body.expected_profile_revision
                or ((row.revision if row else 0) != body.expected_revision)
            ):
                raise HTTPException(409, "Profil oder Agentenregeln inzwischen geändert")
            rules = body.rules
            if (
                rules.shell
                and profile.kind != "ssh"
                or rules.mcp
                and profile.kind != "mcp"
                or (
                    rules.http_prefixes
                    and profile.kind not in {"home_assistant", "paperless", "unifi"}
                )
                or rules.file_read_roots
                and profile.kind != "ssh"
            ):
                raise HTTPException(422, "Regeln passen nicht zum Verbindungstyp")
            if rules.mail_recipients and profile.kind != "smtp":
                raise HTTPException(422, "Empfängerregeln benötigen ein SMTP-Profil")
            if row is None:
                row = AgentPolicy(
                    integration_id=profile.id,
                    profile_revision=profile.revision,
                    revision=1,
                    rules=encode(rules.model_dump()),
                )
                db.add(row)
            else:
                row.revision += 1
                row.profile_revision, row.rules = profile.revision, encode(rules.model_dump())
            document = encode(
                {
                    "revision": row.revision,
                    "profile_revision": row.profile_revision,
                    "rules": rules.model_dump(),
                    "source": "authenticated_human",
                }
            )
            db.add(
                AgentPolicyEvent(
                    integration_id=profile.id, document=document, sha256=digest(document)
                )
            )
            db.commit()
            return {
                "revision": row.revision,
                "profile_revision": row.profile_revision,
                "rules": rules.model_dump(),
                "current": True,
            }

    @app.post("/api/conversations/{conversation_id}/agent-runs")
    async def start(conversation_id: UUID, body: StartInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            owner = db.get(Conversation, str(conversation_id))
            if not owner or owner.archived or owner.purpose != "chat":
                raise HTTPException(404, "Aktives Gespräch erforderlich")
            old = db.scalar(select(AgentJob).where(AgentJob.request_id == str(body.request_id)))
            parts = project_context(db, owner.project_id, body.goal) if owner.project_id else []
            if not old:
                from hub.policy import ContextPart

                history = list(
                    db.scalars(
                        select(Message)
                        .where(Message.conversation_id == owner.id, Message.active.is_(True))
                        .order_by(Message.created.desc(), Message.id.desc())
                        .limit(12)
                    )
                )
                parts.extend(
                    ContextPart(
                        content="Gesprächsdaten (" + message.role + "): " + message.content[:4000],
                        source_id="agent-history:" + message.id,
                        revision=message.revision,
                    )
                    for message in reversed(history)
                )
            elif old.context:
                # Replays bind the original local history, not messages appended
                # by this very run after its initial request.
                from hub.policy import ContextPart

                parts.extend(
                    ContextPart.model_validate(part)
                    for part in json.loads(old.context)
                    if part["source_id"].startswith("agent-history:")
                )
            if body.reconcile_job_id:
                from hub.agent_runtime import steps
                from hub.policy import ContextPart

                previous = db.get(AgentJob, str(body.reconcile_job_id))
                if (
                    not previous
                    or previous.conversation_id != owner.id
                    or previous.status != "uncertain"
                    or (not body.read_only or body.research_allowed)
                ):
                    raise HTTPException(
                        409,
                        "Abgleich benötigt einen unklaren Auftrag im selben Gespräch "
                        "und bleibt lokal lesend",
                    )
                # Prior tool arguments remain private data, never public query material.
                parts.extend(
                    ContextPart(
                        content="Unklarer früherer Werkzeugauftrag (nur Daten): " + s.document,
                        source_id="agent-effect:" + previous.id + ":" + str(s.sequence),
                        revision=1,
                    )
                    for s in steps(db, previous.id)
                    if s.kind == "effect"
                )
            job = create_job(
                db,
                cfg,
                scope="conversation",
                owner_id=owner.id,
                conversation_id=owner.id,
                request_id=str(body.request_id),
                goal=body.goal,
                research_allowed=body.research_allowed,
                read_only=body.read_only,
                context=[p.model_dump(mode="json") for p in parts],
            )
            if not old:
                db.add(
                    Message(
                        conversation_id=owner.id, role="user", content=body.goal, label="LOCAL_ONLY"
                    )
                )
                enqueue_agent(db, cfg, job.id)
            db.commit()
            result = job_info(db, job)
        if not old:
            start_development_agent(app, cfg, factory, result["id"])
        return result

    @app.get("/api/agent-runs")
    def listing(
        auth: Auth, conversation_id: UUID | None = None, task_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        with factory() as db:
            query = select(AgentJob).order_by(AgentJob.created.desc()).limit(5)
            if conversation_id:
                query = query.where(AgentJob.conversation_id == str(conversation_id))
            if task_id:
                query = query.where(AgentJob.scope == "task", AgentJob.owner_id == str(task_id))
            return [job_info(db, job, compact=True) for job in db.scalars(query)]

    @app.get("/api/agent-runs/{job_id}/steps/{sequence}")
    def get_step(job_id: UUID, sequence: int, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            step = db.get(AgentStep, (str(job_id), sequence))
            if not step or not db.get(AgentJob, str(job_id)):
                raise HTTPException(404, "Agentenbeleg fehlt")
            return {
                "document": json.loads(step.document),
                "result": json.loads(step.result),
                "sha256": step.sha256,
                "label": "LOCAL_ONLY",
            }

    @app.get("/api/agent-runs/{job_id}")
    def get(job_id: UUID, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            job = db.get(AgentJob, str(job_id))
            if not job:
                raise HTTPException(404, "Agentenlauf fehlt")
            return job_info(db, job)

    @app.post("/api/agent-runs/{job_id}/approve")
    async def approve(job_id: UUID, body: ApprovalInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            job = db.get(AgentJob, str(job_id))
            step = db.get(AgentStep, (str(job_id), body.sequence))
            if (
                not job
                or job.status != "awaiting_approval"
                or not step
                or (
                    step.kind != "effect"
                    or step.status != "prepared"
                    or step.sha256 != body.sha256
                    or digest(step.document) != step.sha256
                )
            ):
                raise HTTPException(409, "Aktionsvorschlag geändert oder nicht mehr freigebbar")
            checked_gate(db, job, effect=True)
            step.approved, job.status = True, "queued"
            enqueue_agent(db, cfg, job.id)
            db.commit()
            result = job_info(db, job)
        start_development_agent(app, cfg, factory, result["id"])
        return result

    @app.post("/api/agent-runs/{job_id}/reply")
    async def reply(job_id: UUID, body: ReplyInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            job = db.get(AgentJob, str(job_id))
            step = db.get(AgentStep, (str(job_id), body.sequence))
            from hub.agent_runtime import steps

            if (
                not job
                or job.status != "awaiting_input"
                or not step
                or step.sha256 != body.sha256
                or (steps(db, job.id)[-1].sequence != step.sequence)
            ):
                raise HTTPException(409, "Rückfrage inzwischen geändert")
            checked_gate(db, job)
            record(db, job, "input", {"content": body.content}).status = "succeeded"
            db.add(
                Message(
                    conversation_id=job.conversation_id,
                    role="user",
                    content=body.content,
                    label="LOCAL_ONLY",
                )
            )
            job.status = "queued"
            enqueue_agent(db, cfg, job.id)
            db.commit()
            result = job_info(db, job)
        start_development_agent(app, cfg, factory, result["id"])
        return result

    @app.post("/api/agent-runs/{job_id}/cancel")
    def cancel(job_id: UUID, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            job = db.get(AgentJob, str(job_id))
            if not job:
                raise HTTPException(404, "Agentenlauf fehlt")
            if job.status in ACTIVE:
                job.cancel_requested = True
                for run in db.scalars(
                    select(Run).where(
                        Run.conversation_id == job.model_conversation_id,
                        Run.status.in_({"queued", "routing", "streaming"}),
                    )
                ):
                    run.cancel_requested = True
                if job.status != "running":
                    complete(db, job, "cancelled", "Agentenlauf abgebrochen.")
            db.commit()
            return job_info(db, job)
