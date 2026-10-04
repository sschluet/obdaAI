import asyncio
import json
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from hub.auth import check_origin, require_session, token_hash, verify_password
from hub.config import Settings
from hub.db import Conversation, LoginSession, Message, Run, session_factory
from hub.policy import CloudGrant, ContextPart, Privacy
from hub.providers import Providers
from hub.routing import Capability

SessionDependency = Annotated[LoginSession, Depends(require_session)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    password: str = Field(min_length=1, max_length=256)


class ChatInput(Input):
    content: str = Field(min_length=1, max_length=16000)


class ConversationInput(Input):
    cloud_allowed: bool = False


class ConversationEdit(Input):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    archived: bool | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    factory = session_factory(cfg.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Restart never silently resumes an HTTP-bound generation.
        with factory() as db:
            for run in db.scalars(select(Run).where(Run.status.in_(["routing", "streaming"]))):
                run.status = "interrupted"
                run.error = "Serverneustart; Antwort unterbrochen"
                run.finished = time.time()
            db.commit()
        yield

    app = FastAPI(title="Personal AI Hub", version="0.1.0-dev", lifespan=lifespan)
    app.state.settings = cfg
    app.state.sessions = factory
    app.state.providers = Providers(cfg)
    app.state.login_attempts = []

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
        return {"status": "ok", "milestone": "M1-partial", "privacy_default": "LOCAL_ONLY"}

    @app.post("/api/login")
    def login(body: LoginInput, request: Request, response: Response) -> dict[str, str]:
        check_origin(request)
        now = time.time()
        app.state.login_attempts = [t for t in app.state.login_attempts if now - t < 60]
        if len(app.state.login_attempts) >= 5:
            raise HTTPException(429, "Bitte eine Minute warten")
        app.state.login_attempts.append(now)
        if not cfg.password_hash:
            raise HTTPException(503, "Login ist noch nicht serverseitig eingerichtet")
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
            "version": "0.1.0-dev",
            "autonomous_changes": "paused",
        }

    @app.get("/api/conversations")
    def list_chats(
        session: SessionDependency, q: str = "", archived: bool = False
    ) -> list[dict[str, object]]:
        with factory() as db:
            chats = db.scalars(
                select(Conversation)
                .where(Conversation.archived == archived)
                .order_by(Conversation.created.desc())
            ).all()
            return [
                {
                    "id": c.id,
                    "title": c.title,
                    "cloud_allowed": c.cloud_allowed,
                    "archived": c.archived,
                }
                for c in chats
                if q.lower() in c.title.lower()
            ]

    @app.post("/api/conversations")
    def new_chat(body: ConversationInput, session: SessionDependency) -> dict[str, object]:
        if body.cloud_allowed and not cfg.cloud_enabled:
            raise HTTPException(409, "Cloud ist serverseitig noch nicht freigegeben")
        with factory() as db:
            c = Conversation(cloud_allowed=body.cloud_allowed)
            db.add(c)
            db.commit()
            return {"id": c.id, "title": c.title, "cloud_allowed": c.cloud_allowed}

    @app.get("/api/conversations/{chat_id}")
    def get_chat(chat_id: str, session: SessionDependency) -> dict[str, object]:
        with factory() as db:
            c = db.get(Conversation, chat_id)
            if not c:
                raise HTTPException(404, "Gespräch nicht gefunden")
            messages = db.scalars(
                select(Message).where(Message.conversation_id == chat_id).order_by(Message.created)
            ).all()
            runs = db.scalars(
                select(Run).where(Run.conversation_id == chat_id).order_by(Run.started)
            ).all()
            return {
                "id": c.id,
                "title": c.title,
                "cloud_allowed": c.cloud_allowed,
                "messages": [
                    {"id": m.id, "role": m.role, "content": m.content, "label": m.label}
                    for m in messages
                ],
                "runs": [
                    {
                        "id": x.id,
                        "status": x.status,
                        "provider": x.provider,
                        "reason": x.reason,
                        "error": x.error,
                        "cost": x.cost,
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
                c.title, c.manual_title = body.title, True
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
                select(Run).where(
                    Run.conversation_id == chat_id, Run.status.in_(["routing", "streaming"])
                )
            ):
                raise HTTPException(409, "Lauf zuerst abbrechen")
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
            db.commit()
        return {"ok": True}

    @app.post("/api/conversations/{chat_id}/messages")
    async def send(
        chat_id: str, body: ChatInput, request: Request, session: SessionDependency
    ) -> StreamingResponse:
        if not body.content.strip():
            raise HTTPException(422, "Nachricht ist leer")
        with factory() as db:
            c = db.get(Conversation, chat_id)
            if not c or c.archived:
                raise HTTPException(404, "Aktives Gespräch nicht gefunden")
            label = Privacy.CLOUD_ALLOWED if c.cloud_allowed else Privacy.LOCAL_ONLY
            db.add(Message(conversation_id=chat_id, role="user", content=body.content, label=label))
            run = Run(conversation_id=chat_id)
            db.add(run)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, "In diesem Gespräch läuft bereits eine Antwort") from None
            run_id = run.id
            messages = db.scalars(
                select(Message).where(Message.conversation_id == chat_id).order_by(Message.created)
            ).all()
            if len(messages) > 40 or sum(len(m.content) for m in messages) > 24000:
                run.status, run.error, run.finished = (
                    "failed",
                    "Kontextgrenze erreicht",
                    time.time(),
                )
                db.commit()
                raise HTTPException(413, "Kontextgrenze erreicht; neues Gespräch starten")
            parts = [
                ContextPart(content=m.content, label=Privacy(m.label), source_id=m.id, revision=1)
                for m in messages
            ]
            roles = [m.role for m in messages]
            grants = (
                [
                    CloudGrant(source_id=p.source_id, revision=1, provider_id="openrouter")
                    for p in parts
                ]
                if c.cloud_allowed
                else []
            )

        def event(kind: str, value: object) -> str:
            return "event: " + kind + "\ndata: " + json.dumps(value, ensure_ascii=False) + "\n\n"

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

        async def generate() -> AsyncIterator[str]:
            output = ""
            status = "failed"
            started = time.monotonic()
            yield event("run", {"id": run_id})
            yield event("status", {"message": "Anfrage wird lokal eingeordnet"})
            try:
                async with asyncio.timeout(90):
                    route = await app.state.providers.route(parts, roles)
                    update(router_seconds=time.monotonic() - started, reason=route.reason)
                    if cancelled() or await request.is_disconnected():
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
                        yield event(
                            "status", {"message": "Datenschutzregel hält diese Antwort lokal"}
                        )
                    provider = "openrouter" if external else "local"
                    update(status="streaming", provider=provider)
                    yield event("provider", {"name": provider, "reason": route.reason})
                    if route.answer:
                        output = route.answer
                        update(first_content_seconds=time.monotonic() - started)
                        yield event("delta", {"text": output})
                    else:
                        async for chunk in app.state.providers.stream(
                            parts, roles, external=external, grants=grants
                        ):
                            if cancelled() or await request.is_disconnected():
                                raise asyncio.CancelledError
                            if not output:
                                update(first_content_seconds=time.monotonic() - started)
                            output += chunk
                            if len(output) > 32000:
                                raise ValueError("Output limit exceeded")
                            yield event("delta", {"text": chunk})
                    if not output:
                        raise ValueError("Empty provider response")
                    status = "succeeded"
            except asyncio.CancelledError:
                status = "cancelled"
            except NotImplementedError:
                update(error="Benötigte Werkzeuge sind in diesem Meilenstein noch nicht verfügbar")
                yield event(
                    "error",
                    {
                        "message": "Diese Anfrage benötigt Funktionen aus M2–M4. "
                        "Es wurde kein Werkzeug ausgeführt."
                    },
                )
            except Exception:
                update(error="Provider nicht verfügbar oder ungültige Antwort")
                yield event(
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
                    db.commit()
            yield event("done", {"status": status})

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
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
