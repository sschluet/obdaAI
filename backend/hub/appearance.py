"""Private display preferences. Never included in model context or search indexes.

Avatar bytes are normalized to remove metadata and stored in the private application
DB alongside display names, not in public assets or the personal AI profile.
"""

import base64
import binascii
import io
import warnings
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import ConfigDict, Field, field_validator
from sqlalchemy import Integer, Text, text
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from hub.action_api import StrictInput
from hub.db import Base
from hub.knowledge_api import Auth

MAX_AVATAR_BYTES = 150 * 1024


class AppearanceSettings(Base):
    __tablename__ = "appearance_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    app_name: Mapped[str] = mapped_column(Text, default="obdaAI")
    display_name: Mapped[str] = mapped_column(Text, default="")
    avatar_data_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    density: Mapped[str] = mapped_column(Text, default="compact")
    accent: Mapped[str] = mapped_column(Text, default="indigo")


class AppearanceOptions(StrictInput):
    model_config = ConfigDict(extra="forbid", strict=True)
    app_name: str = Field(default="obdaAI", min_length=1, max_length=48)
    display_name: str = Field(default="", max_length=80)
    avatar_data_url: str | None = Field(default=None, max_length=205000, repr=False)
    density: Literal["compact", "comfortable"] = "compact"
    accent: Literal["indigo", "blue", "teal", "rose"] = "indigo"

    @field_validator("app_name", "display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("Name enthält ungültige Zeichen")
        return value

    @field_validator("app_name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Bitte einen Namen für den Arbeitsraum eingeben")
        return value

    @field_validator("avatar_data_url")
    @classmethod
    def image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        prefixes = {
            "data:image/png;base64,": "PNG",
            "data:image/jpeg;base64,": "JPEG",
            "data:image/webp;base64,": "WEBP",
        }
        prefix = next((p for p in prefixes if value.startswith(p)), None)
        if prefix is None:
            raise ValueError("Foto muss PNG, JPEG oder WebP sein")
        try:
            raw = base64.b64decode(value[len(prefix) :], validate=True)
            if not raw or len(raw) > MAX_AVATAR_BYTES:
                raise ValueError("Foto auf 150 KB begrenzen")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format != prefixes[prefix] or getattr(image, "n_frames", 1) != 1:
                        raise ValueError("Fotoformat ungültig; keine Animationen")
                    if max(image.size) > 512 or min(image.size) < 1:
                        raise ValueError("Foto auf höchstens 512 Pixel begrenzen")
                    image.load()
                    clean = Image.new("RGBA" if image.mode == "RGBA" else "RGB", image.size)
                    clean.paste(image.convert(clean.mode))
                    buffer = io.BytesIO()
                    clean.save(buffer, format=prefixes[prefix])
                    normalized = buffer.getvalue()
                    if len(normalized) > MAX_AVATAR_BYTES:
                        raise ValueError("Foto auf 150 KB begrenzen")
            return prefix + base64.b64encode(normalized).decode("ascii")
        except (
            binascii.Error,
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise ValueError("Foto ist keine gültige Bilddatei") from exc


class AppearanceInput(AppearanceOptions):
    expected_revision: int = Field(ge=0)


def read_appearance(db: Session) -> dict[str, Any]:
    row = db.get(AppearanceSettings, 1)
    if row is None:
        return {"revision": 0, **AppearanceOptions().model_dump()}
    return {
        "revision": row.revision,
        **{key: getattr(row, key) for key in AppearanceOptions.model_fields},
    }


def install_appearance_api(app: FastAPI, factory: sessionmaker[Session]) -> None:
    @app.get("/api/appearance")
    def get(auth: Auth) -> dict[str, Any]:
        with factory() as db:
            return read_appearance(db)

    @app.put("/api/appearance")
    def put(body: AppearanceInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            if db.bind is not None and db.bind.dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            else:
                db.execute(text("SELECT pg_advisory_xact_lock(791103051)"))
            current = read_appearance(db)
            if current["revision"] != body.expected_revision:
                raise HTTPException(409, "Darstellung inzwischen geändert; neu laden")
            row = db.get(AppearanceSettings, 1)
            if row is None:
                row = AppearanceSettings(id=1)
                db.add(row)
            for key, value in body.model_dump(exclude={"expected_revision"}).items():
                setattr(row, key, value)
            row.revision = body.expected_revision + 1
            db.commit()
            return read_appearance(db)
