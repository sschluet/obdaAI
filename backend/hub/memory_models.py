"""Memory lifecycle metadata in the existing application database."""

import time

from sqlalchemy import Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hub.db import Base, new_id


class MemorySettings(Base):
    __tablename__ = "memory_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    extraction_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[str] = mapped_column(Text, default="{}")


class MemoryCandidate(Base):
    """Pointers only: even pending sensitive quotes stay solely in their source."""

    __tablename__ = "memory_candidates"
    __table_args__ = (
        UniqueConstraint(
            "source_message_id", "source_message_revision", "quote_start", "quote_end", "predicate"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[str] = mapped_column(String(36), default="owner")
    source_message_id: Mapped[str] = mapped_column(String(36), index=True)
    source_message_revision: Mapped[int] = mapped_column(Integer)
    source_conversation_id: Mapped[str] = mapped_column(String(36))
    source_sha256: Mapped[str] = mapped_column(String(64))
    quote_start: Mapped[int] = mapped_column(Integer)
    quote_end: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(24), default="personal")
    fact_type: Mapped[str] = mapped_column(String(24), default="fact")
    subject: Mapped[str] = mapped_column(String(80), default="user")
    predicate: Mapped[str] = mapped_column(String(80), default="other")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    sensitivity: Mapped[str] = mapped_column(String(24), default="private")
    explicit_correction: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    memory_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class MemoryLearningJob(Base):
    __tablename__ = "memory_learning_jobs"
    __table_args__ = (
        UniqueConstraint("source_message_id", "source_message_revision", "extractor_version"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_message_id: Mapped[str] = mapped_column(String(36), index=True)
    source_message_revision: Mapped[int] = mapped_column(Integer)
    source_conversation_id: Mapped[str] = mapped_column(String(36))
    source_sha256: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(80), default="direct-quotes-v1")
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    settings_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    error: Mapped[str] = mapped_column(String(80), default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)
