"""Typed integration drafts and scoped selections; credentials are never public."""

import time

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from hub.db import Base, new_id


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[str] = mapped_column(Text)
    encrypted_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_check: Mapped[str | None] = mapped_column(Text, nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class IntegrationBinding(Base):
    __tablename__ = "integration_bindings"
    scope: Mapped[str] = mapped_column(String(20), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    integration_ids: Mapped[str] = mapped_column(Text, default="[]")
    selection_mode: Mapped[str] = mapped_column(String(20), default="manual")
