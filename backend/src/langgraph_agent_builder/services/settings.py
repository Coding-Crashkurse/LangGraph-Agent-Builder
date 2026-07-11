"""Settings — the single configuration loader (SPEC §14).

Precedence (§2.6): CLI flag > process env > --env-file > ./.env > defaults.
CLI flags are applied as explicit constructor kwargs; ``--env-file`` is loaded
into the process env (without overriding it) by the CLI before instantiation.
No other module may read ``os.environ`` directly.
"""

from __future__ import annotations

import secrets as _secrets
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ACCEPTED_MIME = "text/plain,application/json,application/pdf,image/*"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LGA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "prod", "test"] = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    home: Path = Field(default_factory=lambda: Path.home() / ".lga")
    database_url: str = ""  # resolved against `home` when empty (SQLite tier)
    secret_key: str = ""  # Fernet key; auto-generated+persisted in dev, required in prod
    host_url: str = ""  # public base URL; defaults to http://{host}:{port}
    components_path: str = ""  # extra component dirs, os.pathsep-separated
    frontend_path: str = ""  # dev override for bundled _static
    log_level: str = "info"
    auth_enabled: bool | None = None  # default: False in dev, True in prod

    # A2A
    a2a_task_store: str = "db"  # db | memory | "my_pkg.module:factory" (pluggable)
    a2a_blocking_timeout_s: float = 30.0
    a2a_accepted_mime: str = DEFAULT_ACCEPTED_MIME
    a2a_allow_http: bool = False
    a2a_provider_org: str = "lga"
    a2a_provider_url: str = "https://github.com/lga"
    push_allow_private: bool = False

    # MCP
    mcp_timeout_s: float = 120.0

    # misc
    webhook_auth: bool = True
    # LGA_CANCEL_ON_DISCONNECT — cancel a run when its SSE client disconnects (§6.1)
    cancel_on_disconnect: bool = False
    checkpoint_ttl_days: int = 30
    files_dir: Path | None = None
    track_apikey_usage: bool = True
    recursion_limit_default: int = 50

    # Langflow parity (SPEC §18.1)
    load_flows_path: Path | None = None  # FlowSpec *.json imported at boot
    load_flows_overwrite: bool = False
    load_flows_publish: bool = False
    create_starter_flows: bool = True
    auto_saving: bool = True
    auto_saving_interval_ms: int = 1000
    max_file_size_mb: int = 50
    max_text_length: int = 300
    ssl_cert_file: Path | None = None
    ssl_key_file: Path | None = None
    log_file: Path | None = None
    fallback_to_env_var: bool = False  # §9.4 — unresolved $var falls back to process env

    # test-only hooks (never documented)
    testing: bool = False

    # ------------------------------------------------------------------ derived
    @field_validator("home", mode="after")
    @classmethod
    def _expand_home(cls, v: Path) -> Path:
        return v.expanduser()

    @model_validator(mode="after")
    def _fill_defaults(self) -> Settings:
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{(self.home / 'lga.db').as_posix()}"
        if not self.host_url:
            self.host_url = f"http://{self.host}:{self.port}"
        if self.auth_enabled is None:
            self.auth_enabled = self.env == "prod"
        if self.files_dir is None:
            self.files_dir = self.home / "files"
        return self

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql://", "postgresql+"))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def storage_tier(self) -> str:
        return "postgres" if self.is_postgres else "sqlite"

    @property
    def async_database_url(self) -> str:
        """Normalize to an async SQLAlchemy URL regardless of user input scheme."""
        url = self.database_url
        if url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql+psycopg://"):
            return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        return url

    @property
    def psycopg_dsn(self) -> str:
        """Plain libpq DSN for the langgraph Postgres checkpointer."""
        url = self.database_url
        for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
            url = url.replace(prefix, "postgresql://")
        return url

    @property
    def sqlite_db_path(self) -> Path:
        assert self.is_sqlite
        raw = self.async_database_url.split("///", 1)[1]
        return Path(raw)

    def resolve_secret_key(self) -> str:
        """Return the Fernet key; auto-generate + persist in dev, refuse in prod."""
        if self.secret_key:
            return self.secret_key
        if self.env == "prod":
            raise RuntimeError(
                "LGA_SECRET_KEY is required in prod (credentials are encrypted at rest)."
            )
        key_file = self.home / "secret_key"
        if key_file.exists():
            self.secret_key = key_file.read_text(encoding="utf-8").strip()
        else:
            from cryptography.fernet import Fernet

            self.secret_key = Fernet.generate_key().decode()
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_text(self.secret_key, encoding="utf-8")
            if sys.platform != "win32":
                key_file.chmod(0o600)
        return self.secret_key

    def component_dirs(self) -> list[Path]:
        import os

        if not self.components_path:
            return []
        return [Path(p).expanduser() for p in self.components_path.split(os.pathsep) if p]

    @property
    def vectors_dir(self) -> Path:
        """Home of the ``local`` vector store files (SPEC §10.1)."""
        return self.home / "vectors"

    def vectorstore_env_connections(self) -> dict[str, dict[str, Any]]:
        """Parse ``LGA_VECTORSTORE_<NAME>`` JSON descriptors (SPEC §8b.3)."""
        import json
        import os

        prefix = "LGA_VECTORSTORE_"
        out: dict[str, dict[str, Any]] = {}
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            name = key.removeprefix(prefix).lower().replace("_", "-")
            try:
                out[name] = json.loads(value)
            except (ValueError, TypeError):
                continue
        return out

    def ensure_dirs(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        assert self.files_dir is not None
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.vectors_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def new_api_key() -> str:
    return "lga_sk_" + _secrets.token_urlsafe(32)
