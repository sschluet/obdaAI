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
from sqlalchemy import String, case, func, literal_column, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from hub.action_api import install_action_api
from hub.auth import check_origin, require_session, token_hash, verify_password
from hub.config import Settings
from hub.db import (
    Conversation,
    LoginSession,
    LoginThrottle,
    Memory,
    Message,
    Project,
    Run,
    RunEvent,
    Source,
    session_factory,
)
from hub.execution import execute_run
from hub.jobs import enqueue
from hub.knowledge import context as project_context
from hub.knowledge_api import install_knowledge_api
from hub.memory import validate_mount
from hub.memory_api import install_memory_api
from hub.policy import ContextPart, Privacy
from hub.provider_api import install_provider_api
from hub.providers import Providers
from hub.skill_api import install_skill_api, select_skills
from hub.task_api import install_task_api
from hub.websearch import install_web_api

ACTIVE_STATUSES = ["queued", "routing", "streaming"]

SessionDependency = Annotated[LoginSession, Depends(require_session)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    password: str = Field(min_length=1, max_length=256)


class ChatInput(Input):
    web_search_allowed: bool = False
    content: str = Field(min_length=1, max_length=16000)
    request_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")


class ConversationInput(Input):
    memory_scope: Literal["global"] | None = None
    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    cloud_allowed: bool = False


class ConversationEdit(Input):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    archived: bool | None = None


class RetryInput(Input):
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
    install_provider_api(app, cfg, factory)
    install_knowledge_api(app, cfg, factory)
    install_memory_api(app, cfg, factory)
    install_web_api(app, cfg, factory)
    install_action_api(app, factory)
    install_skill_api(app, factory)
    install_task_api(app, cfg, factory)

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
                    func.count(Run.cost),
                    func.sum(Run.cost),
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
                "cost_unknown_runs": sum(statuses.values()) - timings[3],
                "privacy_default": "LOCAL_ONLY",
            }

    @app.post("/api/login")
    def login(body: LoginInput, request: Request, response: Response) -> dict[str, str]:
        check_origin(request)
        now = time.time()
        if not cfg.password_hash:
            raise HTTPException(503, "Login ist noch nicht serverseitig eingerichtet")
        with factory() as db:
            count = db.scalar(
                update(LoginThrottle)
                .where(LoginThrottle.id == 1)
                .values(
                    attempts=case(
                        (LoginThrottle.window < now - 60, 1), else_=LoginThrottle.attempts + 1
                    ),
                    window=case((LoginThrottle.window < now - 60, now), else_=LoginThrottle.window),
                )
                .returning(LoginThrottle.attempts)
            )
            db.commit()
        if count is None or count > 5:
            raise HTTPException(429, "Bitte eine Minute warten")
        if not verify_password(body.password, cfg.password_hash):
            raise HTTPException(401, "Anmeldung fehlgeschlagen")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with factory() as db:
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
        return {
            "local_configured": bool(cfg.local_base_url and cfg.local_model),
            "cloud_enabled": cfg.cloud_enabled,
            "privacy_default": "LOCAL_ONLY",
            "providers": ["local", "openrouter"],
            "web_search_configured": bool(cfg.search_url),
            "version": "0.1.0-dev",
            "autonomous_changes": "paused",
        }

    @app.get("/api/conversations")
    def list_chats(
        session: SessionDependency, q: str = "", archived: bool = False
    ) -> list[dict[str, object]]:
        with factory() as db:
            statement = select(Conversation).where(Conversation.archived == archived)
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
                    "archived": c.archived,
                }
                for c in chats
            ]

    @app.post("/api/conversations")
    def new_chat(body: ConversationInput, session: SessionDependency) -> dict[str, object]:
        if body.cloud_allowed and not cfg.cloud_enabled:
            raise HTTPException(409, "Cloud ist serverseitig noch nicht freigegeben")
        with factory() as db:
            if body.project_id:
                project = db.get(Project, body.project_id)
                if not project or project.archived:
                    raise HTTPException(404, "Aktives Projekt nicht gefunden")
                if body.cloud_allowed:
                    raise HTTPException(409, "Projektquellen bleiben LOCAL_ONLY")
            if body.memory_scope and (body.cloud_allowed or body.project_id):
                raise HTTPException(409, "Vault-Wissenschat nur lokal und ohne Projektmischung")
            c = Conversation(
                cloud_allowed=body.cloud_allowed,
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
            return {
                "id": c.id,
                "project_id": c.project_id,
                "memory_scope": c.memory_scope,
                "title": c.title,
                "title_status": c.title_status,
                "cloud_allowed": c.cloud_allowed,
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
                        "error": x.error,
                        "cost": x.cost,
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
            c = db.get(Conversation, chat_id)
            if not c:
                raise HTTPException(404, "Gespräch nicht gefunden")
            if body.title is not None:
                c.title, c.manual_title, c.title_status = body.title, True, "manual"
            if body.archived is not None:
                c.archived = body.archived
            db.commit()
        return {"ok": True}

    @app.delete("/api/conversations/{chat_id}")
    def delete_chat(chat_id: str, session: SessionDependency) -> dict[str, bool]:
        with factory() as db:
            c = db.get(Conversation, chat_id)
            if not c:
                raise HTTPException(404, "Gespräch nicht gefunden")
            if db.scalar(
                select(Run).where(Run.conversation_id == chat_id, Run.status.in_(ACTIVE_STATUSES))
            ):
                raise HTTPException(409, "Lauf zuerst abbrechen")
            for run in db.scalars(select(Run).where(Run.conversation_id == chat_id)):
                for entry in db.scalars(select(RunEvent).where(RunEvent.run_id == run.id)):
                    db.delete(entry)
            db.flush()
            for model in (Message, Run):
                for row in db.scalars(select(model).where(model.conversation_id == chat_id)):
                    db.delete(row)
            db.delete(c)
            db.commit()
        return {"ok": True}

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str, session: SessionDependency) -> dict[str, bool]:
        with factory() as db:
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
            web_search_allowed=body.web_search_allowed,
        )
        start_development_run(run_id)
        return response_for(run_id, request)

    def create_run(
        chat_id: str,
        request_id: str | None,
        *,
        content: str | None = None,
        web_search_allowed: bool = False,
        edit: tuple[str, MessageEdit] | None = None,
    ) -> str:
        action = {
            "chat_id": chat_id,
            "content": content,
            "web_search_allowed": web_search_allowed,
            "edit": [edit[0], edit[1].model_dump()] if edit else None,
        }
        digest = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()
        with factory() as db:
            if request_id:
                previous = db.scalar(select(Run).where(Run.request_key == request_id))
                if previous:
                    if previous.conversation_id != chat_id or previous.request_digest != digest:
                        raise HTTPException(409, "Anfrage-ID gehört zu anderem Gespräch")
                    return previous.id
            c = db.scalar(select(Conversation).where(Conversation.id == chat_id).with_for_update())
            if not c or c.archived:
                raise HTTPException(404, "Aktives Gespräch nicht gefunden")
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
                target.label = Privacy.CLOUD_ALLOWED if change.cloud_allowed else Privacy.LOCAL_ONLY
            elif content is not None:
                new = Message(
                    conversation_id=chat_id,
                    role="user",
                    content=content,
                    label=Privacy.CLOUD_ALLOWED if c.cloud_allowed else Privacy.LOCAL_ONLY,
                )
                db.add(new)
                db.flush()
                messages.append(new)
            else:
                target = next((m for m in reversed(messages) if m.role == "user"), None)
                if target is None:
                    raise HTTPException(409, "Keine Nachricht zum Wiederholen vorhanden")
                cut = messages.index(target)
                for old in messages[cut + 1 :]:
                    old.active = False
                messages = messages[: cut + 1]
            if len(messages) > 40 or sum(len(m.content) for m in messages) > 24000:
                raise HTTPException(413, "Kontextgrenze erreicht; neues Gespräch starten")
            snapshot: dict[str, Any] = {
                "web_search_allowed": web_search_allowed,
                "parts": [
                    ContextPart(
                        content=m.content,
                        label=Privacy(m.label),
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
            snapshot["parts"].extend(p.model_dump(mode="json") for p in skill_parts)
            snapshot["roles"].extend("user" for _ in skill_parts)
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
        run_id = create_run(chat_id, body.request_id)
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
            web_search_allowed=body.web_search_allowed,
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
                "cost_estimate": run.cost_estimate,
                "model": run.model,
                "provider_revision": run.provider_revision,
                "capabilities": json.loads(run.capabilities),
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
