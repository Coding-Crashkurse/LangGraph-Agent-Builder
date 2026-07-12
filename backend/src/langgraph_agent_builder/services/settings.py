"""Settings — the single configuration loader (env prefix ``BUILDER_``).

The builder is a design-time tool: it needs its own persistence for drafts,
the gateway URL of the agentplane runtime API, and (optionally) OIDC settings
for the shared Keycloak realm. No other module reads ``os.environ`` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BUILDER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "prod", "test"] = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    home: Path = Field(default_factory=lambda: Path.home() / ".langgraph-agent-builder")
    database_url: str = ""  # resolved against `home` when empty (SQLite)
    host_url: str = ""  # public base URL of the builder itself
    frontend_path: str = ""  # dev override for the bundled _static frontend
    log_level: str = "info"

    # agentplane runtime API — always a gateway URL, never an internal address.
    runtime_url: str = ""
    # Static bearer for dev setups without OIDC (auth_mode=none). With
    # auth_mode=oidc the caller's token is forwarded instead.
    runtime_token: str = ""

    # OIDC (shared Keycloak realm). The backend validates JWTs; the frontend
    # runs Authorization Code + PKCE against the same issuer.
    auth_mode: Literal["none", "oidc"] = "none"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_client_id: str = ""  # public client id used by the frontend

    # Links into the platform UI (agentplane-ui); shown as "Manage in
    # Resources" and as the registry link after publish.
    resources_ui_url: str = ""
    registry_ui_url: str = ""

    @field_validator("home", mode="after")
    @classmethod
    def _expand_home(cls, v: Path) -> Path:
        return v.expanduser()

    @model_validator(mode="after")
    def _fill_defaults(self) -> Settings:
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{(self.home / 'builder.db').as_posix()}"
        if not self.host_url:
            self.host_url = f"http://{self.host}:{self.port}"
        if self.auth_mode == "oidc" and not self.oidc_issuer:
            raise ValueError("BUILDER_OIDC_ISSUER is required when BUILDER_AUTH_MODE=oidc")
        return self

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return url

    def ensure_dirs(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
