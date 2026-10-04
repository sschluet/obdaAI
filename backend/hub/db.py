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


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(160), default="Neues Gespräch")
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
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="routing")
    provider: Mapped[str] = mapped_column(String(40), default="local")
    reason: Mapped[str] = mapped_column(String(240), default="")
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started: Mapped[float] = mapped_column(Float, default=time.time)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)
    router_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_content_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
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
