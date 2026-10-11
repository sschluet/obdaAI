import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, func, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from hub.account_api import install_account_api
from hub.action_api import install_action_api
from hub.appearance import install_appearance_api
from hub.artifact_api import install_artifact_api
from hub.artifact_drafts import install_artifact_drafts
from hub.auth import (
    check_origin,
    consume_auth_attempt,
    locked_credential,
    require_session,
    token_hash,
    verify_password,
)
from hub.config import Settings
from hub.connection_api import install_connection_api
from hub.db import (
    Conversation,
    LoginSession,
    Memory,
    Message,
    Project,
    Run,
    RunEvent,
    Source,
    session_factory,
)
from hub.db_locks import ownership_lock
from hub.deletion import DeletionInput
from hub.execution import execute_run
from hub.integration_api import freeze_bindings, install_integration_api
from hub.jobs import enqueue
from hub.knowledge import context as project_context
from hub.knowledge_api import install_knowledge_api
from hub.knowledge_connections import install_knowledge_connections
from hub.memory import validate_mount
from hub.memory_api import install_memory_api
from hub.personal_profile import freeze_profile, install_personal_profile_api
from hub.policy import ContextPart, Privacy
from hub.preference_api import install_preference_api
from hub.preferences import resolve as resolve_preferences
from hub.provider_api import install_provider_api
from hub.providers import Providers
from hub.routing_settings import install_routing_settings_api
from hub.routing_settings import read_options as read_routing_options
from hub.schedule_api import install_schedule_api
from hub.skill_api import install_skill_api, select_skills
from hub.task_api import install_task_api
from hub.task_drafts import install_task_drafts
from hub.use_cases import install_use_case_api
from hub.web_settings import endpoint as web_endpoint
from hub.web_settings import install_web_settings_api, read_options
from hub.websearch import install_web_api
from hub.workflow_api import install_workflow_api
from hub.workspace_search import install_workspace_search

ACTIVE_STATUSES = ["queued", "routing", "streaming"]

SessionDependency = Annotated[LoginSession, Depends(require_session)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    password: str = Field(min_length=1, max_length=256)


class ChatInput(Input):
    cloud_allowed: bool | None = None
    cloud_provider: Literal["openrouter", "openai", "anthropic"] | None = None
    local_only: bool = False
    model_local_only: bool = False
    model_cloud_only: bool = False
    web_search_allowed: bool = False
    web_query: str | None = Field(default=None, min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=16000)
    request_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")


class ConversationInput(Input):
    memory_scope: Literal["global"] | None = None
    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    cloud_allowed: bool = False
    cloud_provider: Literal["openrouter", "openai", "anthropic"] = "openrouter"


class ConversationEdit(Input):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    archived: bool | None = None


class RetryInput(Input):
    cloud_allowed: bool | None = None
    cloud_provider: Literal["openrouter", "openai", "anthropic"] | None = None
    local_only: bool = False
    model_local_only: bool = False
    model_cloud_only: bool = False
    web_search_allowed: bool = False
    web_query: str | None = Field(default=None, min_length=1, max_length=500)
    request_id: str = Field(pattern=r"^[0-9a-f-]{36}$")


class MessageEdit(ChatInput):
    revision: int = Field(ge=1)
    cloud_allowed: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    factory = session_factory(cfg.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # SQLite is a development runner; PostgreSQL runs belong to the worker.
        if not cfg.database_url.startswith("sqlite"):
            yield
            return
        with factory() as db:
            ownership_lock(db)
            for run in db.scalars(select(Run).where(Run.status.in_(ACTIVE_STATUSES))):
                run.status = "interrupted"
                run.error = "Serverneustart; Antwort unterbrochen"
                run.finished = time.time()
            db.commit()
        yield
        for task in list(application.state.tasks):
            task.cancel()
        await asyncio.gather(*application.state.tasks, return_exceptions=True)

    app = FastAPI(title="Personal AI Hub", version="0.1.0-dev", lifespan=lifespan)
    install_account_api(app, cfg, factory)
    install_appearance_api(app, factory)
    install_workspace_search(app, factory)
    install_preference_api(app, factory)
    install_provider_api(app, cfg, factory)
    install_knowledge_api(app, cfg, factory)
    from hub.deletion_cleanup import install_cleanup_api

    install_cleanup_api(app, factory)
    install_knowledge_connections(app, cfg, factory)
    install_artifact_api(app, cfg, factory)
    install_artifact_drafts(app, cfg, factory)
    install_memory_api(app, cfg, factory)
    install_web_api(app, cfg, factory)
    install_web_settings_api(app, cfg, factory)
    install_routing_settings_api(app, cfg, factory)
    install_personal_profile_api(app, factory)
    install_action_api(app, factory, cfg)
    install_connection_api(app, cfg, factory)
    install_integration_api(app, cfg, factory)
    install_use_case_api(app, cfg, factory)
    install_skill_api(app, factory)
    install_task_api(app, cfg, factory)
    from hub.task_writes import install_task_writes

    install_task_writes(app, cfg, factory)
    install_schedule_api(app, cfg, factory)
    install_workflow_api(app, cfg, factory)
    install_task_drafts(app, cfg, factory)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError) -> JSONResponse:
        # Never echo raw validation inputs, which may contain provider credentials.
        return JSONResponse(status_code=422, content={"detail": "Ungültige Eingabe"})

    app.state.settings = cfg
    app.state.sessions = factory
    app.state.providers = Providers(cfg)
    app.state.tasks = set()

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "milestone": "M3-partial", "privacy_default": "LOCAL_ONLY"}

    @app.get("/api/metrics")
    def metrics(session: SessionDependency) -> dict[str, object]:
        # Aggregated operational data only; no prompts, keys, titles or session IDs.
        with factory() as db:
            window = Run.started >= time.time() - 30 * 86400
            statuses = dict(
                db.execute(
                    select(Run.status, func.count()).where(window).group_by(Run.status)
                ).all()
            )
            timings = db.execute(
                select(
                    func.avg(Run.router_seconds),
                    func.avg(Run.first_content_seconds),
                    func.avg(Run.finished - Run.started),
                    func.count(Run.cost).filter(Run.cost_basis == "provider_reported"),
                    func.sum(Run.cost).filter(Run.cost_basis == "provider_reported"),
                    func.count(Run.cost).filter(Run.cost_basis == "usage_estimate"),
                    func.sum(Run.cost).filter(Run.cost_basis == "usage_estimate"),
                ).where(window)
            ).one()
            return {
                "window_days": 30,
                "statuses": statuses,
                "router_seconds_avg": timings[0],
                "first_content_seconds_avg": timings[1],
                "duration_seconds_avg": timings[2],
                "measured_cost_runs": timings[3],
                "measured_cost_usd": timings[4],
                "estimated_cost_runs": timings[5],
                "estimated_cost_usd": timings[6],
                "cost_unknown_runs": sum(statuses.values()) - timings[3] - timings[5],
                "privacy_default": "LOCAL_ONLY",
            }

    @app.post("/api/login")
    def login(body: LoginInput, request: Request, response: Response) -> dict[str, str]:
        check_origin(request)
        now = time.time()
        consume_auth_attempt(factory, 1, now)
        with factory() as db:
            credential = locked_credential(db)
            stored = credential.password_hash or cfg.password_hash
            if not stored:
                raise HTTPException(503, "Login ist noch nicht serverseitig eingerichtet")
            if not verify_password(body.password, stored):
                raise HTTPException(401, "Anmeldung fehlgeschlagen")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.add(LoginSession(token_hash=token_hash(token), csrf=csrf, expires=now + 43200))
            db.commit()
        response.set_cookie(
            "hub_session",
            token,
            httponly=True,
            secure=cfg.secure_cookie,
            samesite="strict",
            max_age=43200,
        )
        return {"csrf": csrf}

    @app.get("/api/me")
    def me(session: SessionDependency) -> dict[str, str]:
        return {"csrf": session.csrf}

    @app.post("/api/logout")
    def logout(session: SessionDependency, response: Response) -> dict[str, bool]:
        with factory() as db:
            db.delete(db.get(LoginSession, session.token_hash))
            db.commit()
        response.delete_cookie("hub_session", secure=cfg.secure_cookie, samesite="strict")
        return {"ok": True}

    @app.get("/api/settings")
    def settings_info(session: SessionDependency) -> dict[str, object]:
        with factory() as db:
            web = read_options(db)
        return {
            "local_configured": bool(cfg.local_base_url and cfg.local_model),
            "cloud_enabled": cfg.cloud_enabled,
            "privacy_default": "LOCAL_ONLY",
            "providers": ["local", "openrouter", "openai", "anthropic"],
            "external_provider_kinds": list(cfg.external_provider_kinds),
            "web_search_configured": bool(web_endpoint(cfg)) and web["enabled"],
            "web_search_endpoint_configured": bool(web_endpoint(cfg)),
            "version": "0.1.0-dev",
            "autonomous_changes": "paused",
        }

    @app.get("/api/conversations")
    def list_chats(
        session: SessionDependency,
        q: str = "",
        archived: bool = False,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        with factory() as db:
            ownership_lock(db)
            statement = select(Conversation).where(Conversation.archived == archived)
            if project_id:
                if not db.get(Project, project_id):
                    raise HTTPException(404, "Projektraum nicht gefunden")
                statement = statement.where(Conversation.project_id == project_id)
            title_match: ColumnElement[bool]
            message_match: ColumnElement[bool]
            if q:
                if len(q) > 200:
                    raise HTTPException(422, "Suchtext zu lang")
                if db.bind is not None and db.bind.dialect.name == "postgresql":
                    config: ColumnElement[str] = literal_column("'german'", type_=String())
                    query = func.websearch_to_tsquery(config, q)
                    title_match = func.to_tsvector(config, Conversation.title).op("@@")(query)
                    message_match = func.to_tsvector(config, Message.content).op("@@")(query)
                else:
                    title_match = Conversation.title.icontains(q, autoescape=True)
                    message_match = Message.content.icontains(q, autoescape=True)
                statement = statement.where(
                    or_(
                        title_match,
                        select(Message.id)
                        .where(
                            Message.conversation_id == Conversation.id,
                            Message.active.is_(True),
                            message_match,
                        )
                        .exists(),
                    )
                )
            chats = db.scalars(statement.order_by(Conversation.created.desc()).limit(100)).all()
            return [
                {
                    "id": c.id,
                    "project_id": c.project_id,
                    "memory_scope": c.memory_scope,
                    "title": c.title,
                    "title_status": c.title_status,
                    "cloud_allowed": c.cloud_allowed,
                    "cloud_provider": c.cloud_provider,
                    "archived": c.archived,
                }
                for c in chats
            ]

    @app.post("/api/conversations")
    def new_chat(body: ConversationInput, session: SessionDependency) -> dict[str, object]:
        if body.cloud_allowed and (
            not cfg.cloud_enabled or body.cloud_provider not in cfg.external_provider_kinds
        ):
            raise HTTPException(409, "Cloud ist serverseitig noch nicht freigegeben")
        with factory() as db:
            ownership_lock(db)
            if body.project_id:
                project = db.get(Project, body.project_id)
                if not project or project.archived:
                    raise HTTPException(404, "Aktives Projekt nicht gefunden")
                if project.kind == "knowledge":
                    from hub.knowledge_connections import check_chat_source

                    try:
                        check_chat_source(db, project.id)
                    except ValueError as error:
                        raise HTTPException(409, str(error)) from None
                if body.cloud_allowed:
                    raise HTTPException(409, "Projektquellen bleiben LOCAL_ONLY")
            if body.memory_scope and (body.cloud_allowed or body.project_id):
                raise HTTPException(409, "Vault-Wissenschat nur lokal und ohne Projektmischung")
            c = Conversation(
                cloud_allowed=body.cloud_allowed,
                cloud_provider=body.cloud_provider,
                project_id=body.project_id,
                memory_scope=body.memory_scope,
            )
            db.add(c)
            db.commit()
            return {
                "id": c.id,
                "project_id": c.project_id,
                "memory_scope": c.memory_scope,
                "title": c.title,
                "title_status": c.title_status,
                "cloud_allowed": c.cloud_allowed,
                "cloud_provider": c.cloud_provider,
            }

    @app.get("/api/conversations/{chat_id}")
    def get_chat(chat_id: str, session: SessionDependency) -> dict[str, object]:
        with factory() as db:
            c = db.get(Conversation, chat_id)
            if not c:
                raise HTTPException(404, "Gespräch nicht gefunden")
            messages = db.scalars(
                select(Message)
                .where(Message.conversation_id == chat_id, Message.active.is_(True))
                .order_by(Message.created, Message.id)
            ).all()
            runs = db.scalars(
                select(Run).where(Run.conversation_id == chat_id).order_by(Run.started)
            ).all()
            by_run = {run.id: run for run in runs}
            return {
                "id": c.id,
                "project_id": c.project_id,
                "memory_scope": c.memory_scope,
                "title": c.title,
                "title_status": c.title_status,
                "cloud_allowed": c.cloud_allowed,
                "cloud_provider": c.cloud_provider,
                "context_sources": [
                    {
                        "source_id": part["source_id"],
                        "revision": part["revision"],
                        "label": part["label"],
                        "reference": part["content"].split("\n")[0],
                        "download_url": (
                            f"/api/projects/{c.project_id}/sources/{part['source_id']}/original"
                            if c.project_id and db.get(Source, part["source_id"])
                            else None
                        ),
                    }
                    for part in (
                        json.loads(runs[-1].context_snapshot).get("sources", [])
                        if runs and runs[-1].context_snapshot
                        else []
                    )
                    if part["content"].startswith(("QUELLE [", "VAULT ", "WEBQUELLE "))
                ],
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "label": m.label,
                        "revision": m.revision,
                        "processing": (
                            {
                                "run_id": linked.id,
                                "provider": linked.provider,
                                "model": linked.model or None,
                                "model_used": linked.answer_model_used,
                                "status": linked.status,
                                **(
                                    {"routing": json.loads(linked.routing_trace)}
                                    if linked.routing_trace and linked.routing_trace != "{}"
                                    else {}
                                ),
                            }
                            if m.role == "assistant"
                            and (linked := by_run.get(m.run_id or "")) is not None
                            else None
                        ),
                    }
                    for m in messages
                ],
                "runs": [
                    {
                        "id": x.id,
                        "request_id": x.request_key,
                        "status": x.status,
                        "provider": x.provider,
                        "reason": x.reason,
                        "routing": json.loads(x.routing_trace or "{}"),
                        "error": x.error,
                        "cost": x.cost,
                        "cost_basis": x.cost_basis,
                        "artifact": json.loads(x.context_snapshot or "{}").get("artifact"),
                        "cost_estimate": x.cost_estimate,
                        "model": x.model,
                        "provider_revision": x.provider_revision,
                        "capabilities": json.loads(x.capabilities),
                        "router_seconds": x.router_seconds,
                        "first_content_seconds": x.first_content_seconds,
                    }
                    for x in runs
                ],
            }

    @app.patch("/api/conversations/{chat_id}")
    def edit_chat(
        chat_id: str, body: ConversationEdit, session: SessionDependency
    ) -> dict[str, bool]:
        with factory() as db:
            ownership_lock(db)
            c = db.get(Conversation, chat_id)
            if not c:
                raise HTTPException(404, "Gespräch nicht gefunden")
            if body.title is not None:
                c.title, c.manual_title, c.title_status = body.title, True, "manual"
            if body.archived is not None:
                c.archived = body.archived
            db.commit()
        return {"ok": True}

    @app.get("/api/conversations/{chat_id}/deletion")
    def chat_deletion_preview(chat_id: str, session: SessionDependency) -> dict[str, Any]:
        from hub.deletion import preview

        with factory() as db:
            return preview(db, "conversation", chat_id, cfg)

    @app.delete("/api/conversations/{chat_id}")
    def delete_chat(
        chat_id: str, session: SessionDependency, body: DeletionInput | None = None
    ) -> dict[str, Any]:
        from hub.deletion import permanently_delete

        with factory() as db:
            ownership_lock(db)
            return permanently_delete(db, cfg, "conversation", chat_id, body)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str, session: SessionDependency) -> dict[str, bool]:
        with factory() as db:
            ownership_lock(db)
            run = db.get(Run, run_id)
            if not run:
                raise HTTPException(404, "Lauf nicht gefunden")
            run.cancel_requested = True
            if run.status == "queued":
                run.status, run.finished = "cancelled", time.time()
            db.commit()
        return {"ok": True}

    @app.post("/api/conversations/{chat_id}/messages")
    async def send(
        chat_id: str, body: ChatInput, request: Request, session: SessionDependency
    ) -> StreamingResponse:
        if not body.content.strip():
            raise HTTPException(422, "Nachricht ist leer")
        run_id = create_run(
            chat_id,
            body.request_id,
            content=body.content,
            cloud_allowed=body.cloud_allowed,
            cloud_provider=body.cloud_provider,
            web_search_allowed=body.web_search_allowed,
            web_query=body.web_query,
            local_only=body.local_only,
            model_local_only=body.model_local_only,
            model_cloud_only=body.model_cloud_only,
        )
        start_development_run(run_id)
        return response_for(run_id, request)

    def create_run(
        chat_id: str,
        request_id: str | None,
        *,
        content: str | None = None,
        cloud_allowed: bool | None = None,
        cloud_provider: str | None = None,
        web_search_allowed: bool = False,
        web_query: str | None = None,
        local_only: bool = False,
        model_local_only: bool = False,
        model_cloud_only: bool = False,
        edit: tuple[str, MessageEdit] | None = None,
    ) -> str:
        if model_cloud_only and (local_only or model_local_only or cloud_allowed is False):
            raise HTTPException(422, "Cloud und Nur lokal können nicht kombiniert werden")
        if model_cloud_only:
            cloud_allowed = True
        model_local_only = model_local_only or cloud_allowed is False
        if local_only and web_search_allowed:
            raise HTTPException(422, "Nur lokal erlaubt keine externe Websuche")
        if web_query is not None and (not web_search_allowed or not web_query.strip()):
            raise HTTPException(422, "Öffentlichen Suchtext ausdrücklich bestätigen")
        action = {
            "chat_id": chat_id,
            "content": content,
            "web_search_allowed": web_search_allowed,
            "local_only": local_only,
            "model_local_only": model_local_only,
            "model_cloud_only": model_cloud_only,
            "edit": [
                edit[0],
                edit[1].model_dump(exclude={"web_query"} if edit[1].web_query is None else set()),
            ]
            if edit
            else None,
        }
        if web_query is not None:
            action["web_query"] = web_query
        if cloud_allowed is not None:
            action["cloud_allowed"] = cloud_allowed
        if cloud_provider is not None:
            action["cloud_provider"] = cloud_provider
        digest = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()
        with factory() as db:
            ownership_lock(db)
            if request_id:
                previous = db.scalar(select(Run).where(Run.request_key == request_id))
                if previous:
                    if previous.conversation_id != chat_id or previous.request_digest != digest:
                        raise HTTPException(409, "Anfrage-ID gehört zu anderem Gespräch")
                    return previous.id
            c = db.scalar(select(Conversation).where(Conversation.id == chat_id).with_for_update())
            if not c or c.archived:
                raise HTTPException(404, "Aktives Gespräch nicht gefunden")
            if cloud_allowed and not (local_only or model_local_only):
                provider = cloud_provider or c.cloud_provider
                if not cfg.cloud_enabled or provider not in cfg.external_provider_kinds:
                    raise HTTPException(409, "Cloud ist serverseitig noch nicht freigegeben")
                if c.project_id or c.memory_scope:
                    raise HTTPException(409, "Projekt- und Wissensquellen bleiben LOCAL_ONLY")
                if provider != c.cloud_provider and db.scalar(
                    select(Message.id)
                    .where(Message.conversation_id == chat_id, Message.active.is_(True))
                    .limit(1)
                ):
                    raise HTTPException(
                        409, "Für einen anderen Cloudanbieter ein neues Gespräch starten"
                    )
                # Grant only this input/revision. Existing LOCAL_ONLY history
                # retains its label and can still block the final egress boundary.
                c.cloud_allowed, c.cloud_provider = True, provider
            if db.scalar(
                select(Run.id).where(
                    Run.conversation_id == chat_id, Run.status.in_(ACTIVE_STATUSES)
                )
            ):
                raise HTTPException(409, "In diesem Gespräch läuft bereits eine Antwort")
            messages = list(
                db.scalars(
                    select(Message)
                    .where(Message.conversation_id == chat_id, Message.active.is_(True))
                    .order_by(Message.created, Message.id)
                )
            )
            if edit:
                message_id, change = edit
                target = next(
                    (m for m in messages if m.id == message_id and m.role == "user"), None
                )
                if not target:
                    raise HTTPException(404, "Aktive Benutzernachricht nicht gefunden")
                if target.revision != change.revision:
                    raise HTTPException(409, "Nachricht wurde inzwischen geändert; neu laden")
                if change.cloud_allowed and (not c.cloud_allowed or not cfg.cloud_enabled):
                    raise HTTPException(409, "Cloudfreigabe für diese Änderung fehlt")
                cut = messages.index(target)
                for old in messages[cut + 1 :]:
                    old.active = False
                messages = messages[: cut + 1]
                target.content, target.revision = change.content, target.revision + 1
                target.label = (
                    Privacy.CLOUD_ALLOWED
                    if change.cloud_allowed and not (local_only or model_local_only)
                    else Privacy.LOCAL_ONLY
                )
            elif content is not None:
                new = Message(
                    conversation_id=chat_id,
                    role="user",
                    content=content,
                    label=Privacy.CLOUD_ALLOWED
                    if c.cloud_allowed and not (local_only or model_local_only)
                    else Privacy.LOCAL_ONLY,
                )
                db.add(new)
                db.flush()
                messages.append(new)
            else:
                target = next((m for m in reversed(messages) if m.role == "user"), None)
                if target is None:
                    raise HTTPException(409, "Keine Nachricht zum Wiederholen vorhanden")
                if cloud_allowed and not (local_only or model_local_only):
                    target.label = Privacy.CLOUD_ALLOWED
                cut = messages.index(target)
                for old in messages[cut + 1 :]:
                    old.active = False
                messages = messages[: cut + 1]
            if len(messages) > 40 or sum(len(m.content) for m in messages) > 24000:
                raise HTTPException(413, "Kontextgrenze erreicht; neues Gespräch starten")
            web_options = read_options(db)
            if web_search_allowed and not web_options["enabled"]:
                raise HTTPException(409, "Webrecherche ist in den Einstellungen deaktiviert")
            try:
                personal_profile = freeze_profile(db)
            except ValueError:
                raise HTTPException(
                    409, "Persönliche Informationen beschädigt; in Einstellungen prüfen"
                ) from None
            snapshot: dict[str, Any] = {
                "web_options": web_options,
                "routing_options": read_routing_options(db),
                "personal_profile": personal_profile,
                "response_preferences": resolve_preferences(db, c),
                **(
                    {"web_query": web_query or messages[-1].content.strip()[:500]}
                    if web_search_allowed
                    else {}
                ),
                "web_search_allowed": web_search_allowed,
                "model_local_only": model_local_only,
                "model_cloud_only": model_cloud_only,
                "parts": [
                    ContextPart(
                        content=m.content,
                        label=Privacy.LOCAL_ONLY if local_only else Privacy(m.label),
                        source_id=m.id,
                        revision=m.revision,
                    ).model_dump(mode="json")
                    for m in messages
                ],
                "roles": [m.role for m in messages],
            }
            try:
                needs_vault = c.memory_scope or (
                    c.project_id
                    and db.scalar(
                        select(Memory.id)
                        .where(Memory.project_id == c.project_id, Memory.deleted.is_(False))
                        .limit(1)
                    )
                )
                if needs_vault and cfg.vault_fs_type:
                    validate_mount(Path(cfg.vault_dir), cfg.vault_fs_type)
                sources = project_context(
                    db, c.project_id, messages[-1].content, global_memory=c.memory_scope == "global"
                )
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
            snapshot["sources"] = [p.model_dump(mode="json") for p in sources]
            snapshot["parts"].extend(p.model_dump(mode="json") for p in sources)
            snapshot["roles"].extend("user" for _ in sources)
            skill_parts, skill_audit = select_skills(db, c, messages[-1].content)
            snapshot["skills"] = skill_audit
            snapshot["integration_selection"] = freeze_bindings(db, "conversation", c.id)
            snapshot["parts"].extend(p.model_dump(mode="json") for p in skill_parts)
            snapshot["roles"].extend("user" for _ in skill_parts)
            if local_only or model_local_only:
                for part in snapshot["parts"]:
                    part["label"] = Privacy.LOCAL_ONLY.value
            if model_cloud_only and any(
                p["label"] == Privacy.LOCAL_ONLY.value for p in snapshot["parts"]
            ):
                raise HTTPException(
                    409, "Cloud nicht möglich: geschützte Historie oder Skills bleiben lokal. "
                    "Neues Gespräch beginnen oder Auto/Nur lokal wählen."
                )
            if sum(len(p["content"]) for p in snapshot["parts"]) > cfg.context_limit:
                raise HTTPException(413, "Projektkontext zu groß; Quellen gezielter durchsuchen")
            run = Run(
                conversation_id=chat_id,
                status="queued",
                request_key=request_id,
                context_snapshot=json.dumps(snapshot, ensure_ascii=False),
                request_digest=digest,
            )
            db.add(run)
            try:
                db.flush()
                if not cfg.database_url.startswith("sqlite"):
                    enqueue(db, cfg, run.id)
                db.commit()
            except IntegrityError:
                db.rollback()
                if request_id:
                    previous = db.scalar(
                        select(Run).where(
                            Run.request_key == request_id, Run.conversation_id == chat_id
                        )
                    )
                    if previous and previous.request_digest == digest:
                        return previous.id
                raise HTTPException(409, "In diesem Gespräch läuft bereits eine Antwort") from None
            return run.id

    def start_development_run(run_id: str) -> None:
        if cfg.database_url.startswith("sqlite"):
            task = asyncio.create_task(execute_run(factory, cfg, app.state.providers, run_id))
            app.state.tasks.add(task)
            task.add_done_callback(app.state.tasks.discard)

    def response_for(run_id: str, request: Request) -> StreamingResponse:
        return StreamingResponse(
            watch(run_id, request),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.post("/api/conversations/{chat_id}/retry")
    async def retry(
        chat_id: str, body: RetryInput, request: Request, session: SessionDependency
    ) -> StreamingResponse:
        run_id = create_run(
            chat_id,
            body.request_id,
            local_only=body.local_only,
            cloud_allowed=body.cloud_allowed,
            cloud_provider=body.cloud_provider,
            model_local_only=body.model_local_only,
            model_cloud_only=body.model_cloud_only,
            web_search_allowed=body.web_search_allowed,
            web_query=body.web_query,
        )
        start_development_run(run_id)
        return response_for(run_id, request)

    @app.patch("/api/conversations/{chat_id}/messages/{message_id}")
    async def edit_message(
        chat_id: str,
        message_id: str,
        body: MessageEdit,
        request: Request,
        session: SessionDependency,
    ) -> StreamingResponse:
        if not body.content.strip():
            raise HTTPException(422, "Nachricht ist leer")
        run_id = create_run(
            chat_id,
            body.request_id,
            edit=(message_id, body),
            cloud_allowed=body.cloud_allowed,
            cloud_provider=body.cloud_provider,
            web_search_allowed=body.web_search_allowed,
            web_query=body.web_query,
            local_only=body.local_only,
            model_local_only=body.model_local_only,
            model_cloud_only=body.model_cloud_only,
        )
        start_development_run(run_id)
        return response_for(run_id, request)

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, session: SessionDependency) -> dict[str, object]:
        with factory() as db:
            run = db.get(Run, run_id)
            if not run:
                raise HTTPException(404, "Lauf nicht gefunden")
            return {
                "id": run.id,
                "status": run.status,
                "provider": run.provider,
                "error": run.error,
                "context": json.loads(run.context_snapshot or "{}"),
                "answer": "".join(
                    json.loads(e.payload).get("text", "")
                    for e in db.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == run_id, RunEvent.kind == "delta")
                        .order_by(RunEvent.sequence)
                    )
                ),
                "started": run.started,
                "finished": run.finished,
                "cost": run.cost,
                "cost_basis": run.cost_basis,
                "cost_estimate": run.cost_estimate,
                "model": run.model,
                "provider_revision": run.provider_revision,
                "capabilities": json.loads(run.capabilities),
                "routing": json.loads(run.routing_trace) if run.routing_trace != "{}" else None,
            }

    async def watch(run_id: str, request: Request, after: int = 0) -> AsyncIterator[str]:
        yield "event: run\ndata: " + json.dumps({"id": run_id}) + "\n\n"
        yield 'event: status\ndata: {"message": "Gespeicherten Lauf verfolgen"}\n\n'
        while not await request.is_disconnected():
            with factory() as db:
                events = db.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.sequence > after)
                    .order_by(RunEvent.sequence)
                ).all()
                run = db.get(Run, run_id)
            for entry in events:
                after = entry.sequence
                yield f"id: {after}\nevent: {entry.kind}\ndata: {entry.payload}\n\n"
                if entry.kind == "done":
                    return
            if run and run.status not in ACTIVE_STATUSES and not events:
                yield "event: done\ndata: " + json.dumps({"status": run.status}) + "\n\n"
                return
            await asyncio.sleep(0.1)

    @app.get("/api/runs/{run_id}/events")
    async def run_events(
        run_id: str, request: Request, session: SessionDependency, after: int = 0
    ) -> StreamingResponse:
        with factory() as db:
            if not db.get(Run, run_id):
                raise HTTPException(404, "Lauf nicht gefunden")
        return StreamingResponse(
            watch(run_id, request, max(0, after)), media_type="text/event-stream"
        )

    static = Path(cfg.static_dir)
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        if not (static / "index.html").is_file():
            raise HTTPException(503, "Frontend noch nicht gebaut")
        return FileResponse(static / "index.html")

    return app


app = create_app()
