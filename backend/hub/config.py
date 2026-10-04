import os
from pathlib import Path

from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///.local/hub.sqlite"
    origin: str = "http://127.0.0.1:8765"
    secure_cookie: bool = True
    password_hash: str = ""
    local_base_url: str = ""
    local_model: str = ""
    local_key_file: str = ""
    local_allowed_ip: str = ""
    local_disable_thinking: bool = False
    openrouter_model: str = ""
    openrouter_key_file: str = ""
    cloud_enabled: bool = False
    static_dir: str = "frontend/dist"

    @classmethod
    def from_env(cls) -> "Settings":
        values = {}
        for name in cls.__dataclass_fields__:
            raw = os.getenv("HUB_" + name.upper())
            if raw is not None:
                values[name] = raw
        return TypeAdapter(cls).validate_python(values)


def read_secret(path: str) -> str:
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_mode & 0o077:
        raise ValueError("Secret file must be a private regular file")
    value = p.read_text().strip()
    if not value or len(value) > 4096:
        raise ValueError("Invalid secret file")
    return value
