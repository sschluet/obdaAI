import time
import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return str(uuid.uuid4())


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)


class LoginThrottle(Base):
    __tablename__ = "login_throttle"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    window: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(160), default="Neues Gespräch")
    title_status: Mapped[str] = mapped_column(String(20), default="idle", server_default="idle")
    manual_title: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    cloud_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(20), default="LOCAL_ONLY")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="routing")
    request_key: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    request_digest: Mapped[str] = mapped_column(String(64), default="", server_default="")
    context_snapshot: Mapped[str] = mapped_column(Text, default="", server_default="")
    provider: Mapped[str] = mapped_column(String(40), default="local")
    reason: Mapped[str] = mapped_column(String(240), default="")
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started: Mapped[float] = mapped_column(Float, default=time.time)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)
    router_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_content_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str] = mapped_column(String(240), default="", server_default="")
    provider_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capabilities: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (
        Index(
            "one_active_run_per_chat",
            "conversation_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'routing', 'streaming')"),
            postgresql_where=text("status IN ('queued', 'routing', 'streaming')"),
        ),
    )


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[str] = mapped_column(Text)
    encrypted_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        Index(
            "one_default_provider_per_kind",
            "kind",
            unique=True,
            sqlite_where=text("is_default = true"),
            postgresql_where=text("is_default = true"),
        ),
    )


class ProviderTest(Base):
    __tablename__ = "provider_tests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    result: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ProviderRevision(Base):
    __tablename__ = "provider_revisions"
    provider_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(36), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    ceiling: Mapped[float] = mapped_column(Float)
    measured: Mapped[float | None] = mapped_column(Float, nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class RunEvent(Base):
    __tablename__ = "run_events"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[str] = mapped_column(Text)


def session_factory(url: str) -> sessionmaker[Session]:
    args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=args, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)
