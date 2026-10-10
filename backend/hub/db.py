import time
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
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


class AccountCredential(Base):
    __tablename__ = "account_credentials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    changed: Mapped[float | None] = mapped_column(Float, nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    skill_selection: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(160), default="Neues Gespräch")
    title_status: Mapped[str] = mapped_column(String(20), default="idle", server_default="idle")
    manual_title: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    cloud_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    cloud_provider: Mapped[str] = mapped_column(
        String(20), default="openrouter", server_default="openrouter"
    )
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    routing_trace: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started: Mapped[float] = mapped_column(Float, default=time.time)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)
    router_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_content_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str] = mapped_column(String(240), default="", server_default="")
    answer_model_used: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    provider_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capabilities: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_basis: Mapped[str] = mapped_column(String(30), default="unknown", server_default="unknown")
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


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    label: Mapped[str] = mapped_column(String(20), default="LOCAL_ONLY")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(20), default="project", server_default="project")


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(20), default="LOCAL_ONLY")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str] = mapped_column(String(240), default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    origin_url: Mapped[str] = mapped_column(String(2048), default="", server_default="")
    web_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)


class KnowledgeConnection(Base):
    __tablename__ = "knowledge_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(1000), default="")
    target_ref: Mapped[str] = mapped_column(String(100), default="")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), unique=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="needs_setup")
    indexed: Mapped[int] = mapped_column(Integer, default=0)
    last_indexed: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str] = mapped_column(String(240), default="")
    config: Mapped[str] = mapped_column(Text, default="{}")
    encrypted_secret: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("connection_id", "path"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("knowledge_connections.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000))
    fingerprint: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))


class SourceNetworkRequest(Base):
    __tablename__ = "source_network_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20))
    config: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    expires: Mapped[float] = mapped_column(Float)
    granted: Mapped[bool] = mapped_column(Boolean, default=False)


class SourceChunk(Base):
    __tablename__ = "source_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    locator: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    structured: Mapped[str] = mapped_column(Text, default="")


class SourceReadyEvent(Base):
    __tablename__ = "source_ready_events"
    __table_args__ = (UniqueConstraint("source_id", "source_sha256"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    source_revision: Mapped[int] = mapped_column(Integer)
    source_sha256: Mapped[str] = mapped_column(String(64))
    baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ArtifactRevision(Base):
    __tablename__ = "artifact_revisions"
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), unique=True)
    spec: Mapped[str] = mapped_column(Text)
    spec_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    manifest: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(String(240), default="")
    draft_metadata: Mapped[str] = mapped_column(Text, default="", server_default="")
    chat_metadata: Mapped[str] = mapped_column(Text, default="", server_default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    started: Mapped[float | None] = mapped_column(Float, nullable=True)
    accepted: Mapped[float | None] = mapped_column(Float, nullable=True)


class Memory(Base):
    __tablename__ = "memories"
    origin: Mapped[str] = mapped_column(String(100), default="vault")
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    path: Mapped[str] = mapped_column(String(600), unique=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(20), default="LOCAL_ONLY")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    base_content: Mapped[str] = mapped_column(Text, default="")
    conflict: Mapped[str] = mapped_column(Text, default="")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    writable: Mapped[bool] = mapped_column(Boolean, default=False)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


class MemoryRevision(Base):
    __tablename__ = "memory_revisions"
    memory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Research(Base):
    __tablename__ = "research"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    query: Mapped[str] = mapped_column(String(500))
    results: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ActionPolicy(Base):
    __tablename__ = "action_policy"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class ActionIntent(Base):
    __tablename__ = "action_intents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_key: Mapped[str] = mapped_column(String(36), unique=True)
    tool_id: Mapped[str] = mapped_column(String(80))
    tool_revision: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[str] = mapped_column(Text)
    parameters_sha256: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(20), default="LOCAL_ONLY")
    policy_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ActionGrant(Base):
    __tablename__ = "action_grants"
    action_id: Mapped[str] = mapped_column(ForeignKey("action_intents.id"), primary_key=True)
    parameters_sha256: Mapped[str] = mapped_column(String(64))
    tool_revision: Mapped[int] = mapped_column(Integer)
    policy_revision: Mapped[int] = mapped_column(Integer)
    expires: Mapped[float] = mapped_column(Float)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ActionReceipt(Base):
    __tablename__ = "action_receipts"
    action_id: Mapped[str] = mapped_column(ForeignKey("action_intents.id"), primary_key=True)
    result: Mapped[str] = mapped_column(Text)
    finished: Mapped[float] = mapped_column(Float, default=time.time)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    trusted_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)


class SkillRevision(Base):
    __tablename__ = "skill_revisions"
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    document: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    control_revision: Mapped[int] = mapped_column(Integer, default=1)
    paused: Mapped[bool] = mapped_column(Boolean, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class TaskRevision(Base):
    __tablename__ = "task_revisions"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    spec: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class TaskRun(Base):
    __tablename__ = "task_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_revision: Mapped[int] = mapped_column(Integer)
    control_revision: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(36), unique=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (
        Index(
            "one_active_task_run",
            "task_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running', 'awaiting_approval')"),
            postgresql_where=text("status IN ('queued', 'running', 'awaiting_approval')"),
        ),
    )


class TaskWriteGrant(Base):
    __tablename__ = "task_write_grants"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    task_revision: Mapped[int] = mapped_column(Integer)
    control_revision: Mapped[int] = mapped_column(Integer)
    spec_sha256: Mapped[str] = mapped_column(String(64))
    policy_revision: Mapped[int] = mapped_column(Integer)
    expires: Mapped[float] = mapped_column(Float)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class TaskWriteGrantEvent(Base):
    __tablename__ = "task_write_grant_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    document: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class TaskActionLink(Base):
    __tablename__ = "task_action_links"
    action_id: Mapped[str] = mapped_column(ForeignKey("action_intents.id"), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("task_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)


class TaskStep(Base):
    __tablename__ = "task_steps"
    run_id: Mapped[str] = mapped_column(ForeignKey("task_runs.id"), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(80))
    result: Mapped[str] = mapped_column(Text)
    finished: Mapped[float] = mapped_column(Float, default=time.time)


class TaskSchedule(Base):
    __tablename__ = "task_schedules"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    task_revision: Mapped[int] = mapped_column(Integer)
    control_revision: Mapped[int] = mapped_column(Integer)
    spec_sha256: Mapped[str] = mapped_column(String(64))
    definition: Mapped[str] = mapped_column(Text)
    paused: Mapped[bool] = mapped_column(Boolean, default=True)
    next_due: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    event_cursor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class TaskEventOccurrence(Base):
    __tablename__ = "task_event_occurrences"
    __table_args__ = (UniqueConstraint("task_id", "schedule_revision", "event_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    schedule_revision: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[int] = mapped_column(ForeignKey("source_ready_events.id"))
    status: Mapped[str] = mapped_column(String(20))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), unique=True)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ScheduleOccurrence(Base):
    __tablename__ = "schedule_occurrences"
    __table_args__ = (UniqueConstraint("task_id", "schedule_revision", "due"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    schedule_revision: Mapped[int] = mapped_column(Integer)
    due: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), unique=True)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class SchedulerPulse(Base):
    __tablename__ = "scheduler_pulse"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_tick: Mapped[float] = mapped_column(Float)


class ScheduleRevision(Base):
    __tablename__ = "schedule_revisions"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ToolConnection(Base):
    __tablename__ = "tool_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(80))
    config: Mapped[str] = mapped_column(Text)
    encrypted_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ToolConnectionRevision(Base):
    __tablename__ = "tool_connection_revisions"
    connection_id: Mapped[str] = mapped_column(ForeignKey("tool_connections.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ToolConnectionCheck(Base):
    __tablename__ = "tool_connection_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("tool_connections.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class WorkflowBinding(Base):
    __tablename__ = "workflow_bindings"
    __table_args__ = (UniqueConstraint("task_id", "task_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_revision: Mapped[int] = mapped_column(Integer)
    control_revision: Mapped[int] = mapped_column(Integer)
    spec_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    encrypted_secret: Mapped[str] = mapped_column(Text)
    graph: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_version: Mapped[str | None] = mapped_column(String(36), nullable=True)
    header_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class WorkflowDispatch(Base):
    __tablename__ = "workflow_dispatches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    binding_id: Mapped[str] = mapped_column(ForeignKey("workflow_bindings.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="prepared")
    control_revision: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), unique=True)
    execution_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (
        Index(
            "one_pending_workflow_dispatch",
            "binding_id",
            unique=True,
            sqlite_where=text("status IN ('prepared', 'uncertain')"),
            postgresql_where=text("status IN ('prepared', 'uncertain')"),
        ),
    )


class ResponsePreference(Base):
    __tablename__ = "response_preferences"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)


class ResponsePreferenceRevision(Base):
    __tablename__ = "response_preference_revisions"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    overrides: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class WebSettings(Base):
    __tablename__ = "web_settings"
    __table_args__ = (
        CheckConstraint("id = 1 AND revision >= 0", name="web_settings_singleton"),
        CheckConstraint("language IN ('all', 'de', 'en')", name="web_settings_language"),
        CheckConstraint(
            "safe_search BETWEEN 0 AND 2 AND max_results BETWEEN 1 AND 8 "
            "AND timeout BETWEEN 5 AND 30",
            name="web_settings_limits",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(8), default="all")
    safe_search: Mapped[int] = mapped_column(Integer, default=1)
    max_results: Mapped[int] = mapped_column(Integer, default=8)
    timeout: Mapped[int] = mapped_column(Integer, default=15)


class PersonalProfile(Base):
    __tablename__ = "personal_profile"
    __table_args__ = (
        CheckConstraint("id = 1 AND revision >= 0", name="personal_profile_singleton"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    fields: Mapped[str] = mapped_column(Text, default="{}")
    cloud_fields: Mapped[str] = mapped_column(Text, default="[]")


class RoutingSettings(Base):
    __tablename__ = "routing_settings"
    __table_args__ = (
        CheckConstraint("id = 1 AND revision >= 0", name="routing_settings_singleton"),
        CheckConstraint("strategy IN ('balanced', 'local_first', 'cloud_first')",
                        name="routing_settings_strategy"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    strategy: Mapped[str] = mapped_column(String(16), default="balanced")
    complex_research_cloud: Mapped[bool] = mapped_column(Boolean, default=True)
