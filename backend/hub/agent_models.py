"""Durable administration authority, model turns and one-attempt effects."""

import time

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from hub.db import Base, new_id


class AgentPolicy(Base):
    __tablename__ = "agent_policies"
    integration_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    profile_revision: Mapped[int] = mapped_column(Integer)
    rules: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class AgentJob(Base):
    __tablename__ = "agent_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[str] = mapped_column(String(36))
    conversation_id: Mapped[str] = mapped_column(String(36))
    model_conversation_id: Mapped[str] = mapped_column(String(36))
    task_run_id: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    task_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    control_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goal: Mapped[str] = mapped_column(Text)
    bindings: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="[]")
    research_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    max_steps: Mapped[int] = mapped_column(Integer, default=20)
    max_effects: Mapped[int] = mapped_column(Integer, default=5)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600)
    summary: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (
        Index(
            "one_active_agent_per_scope",
            "scope",
            "owner_id",
            unique=True,
            sqlite_where=text(
                "status IN ('queued','running','awaiting_approval','awaiting_input')"
            ),
            postgresql_where=text(
                "status IN ('queued','running','awaiting_approval','awaiting_input')"
            ),
        ),
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="prepared")
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    document: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(Text, default="{}")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class AgentPolicyEvent(Base):
    __tablename__ = "agent_policy_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    integration_id: Mapped[str] = mapped_column(String(36), index=True)
    document: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time)
