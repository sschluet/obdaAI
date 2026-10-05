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
    local_allowed_labels: tuple[str, ...] = ("LOCAL_ONLY", "CLOUD_ALLOWED")
    local_disable_thinking: bool = False
    openrouter_model: str = ""
    openrouter_key_file: str = ""
    cloud_enabled: bool = False
    secrets_key_file: str = ""
    local_endpoints_json: str = "{}"
    local_timeout: int = 30
    openrouter_timeout: int = 30
    local_max_tokens: int = 2048
    openrouter_max_tokens: int = 2048
    run_timeout: int = 90
    context_limit: int = 24000
    source_dir: str = ".local/sources"
    parser_result_dir: str = ""
    vault_dir: str = ""
    vault_fs_type: str = ""
    vault_writable: bool = False
    web_domains_json: str = "[]"
    search_url: str = ""
    search_allowed_ip: str = ""
    scheduler_enabled: bool = False
    scheduler_token_file: str = ""
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
