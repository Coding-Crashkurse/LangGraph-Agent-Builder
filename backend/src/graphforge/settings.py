"""Environment-driven configuration (pydantic-settings)."""

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://graphforge:graphforge@localhost:55432/graphforge"
    base_url: str = "http://localhost:8000"
    openai_api_key: str | None = None
    embedding_model: str = "openai:text-embedding-3-small"
    enable_grpc: bool = False
    enable_mcp_elicitation: bool = False
    testing: bool = False
    dev_reload_components: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @property
    def psycopg_dsn(self) -> str:
        """Plain libpq DSN for the langgraph checkpointer (psycopg, not SQLAlchemy)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgresql+psycopg://", "postgresql://"
        )

    def export_provider_keys(self) -> None:
        """Provider SDKs read keys from the process env; mirror .env values there."""
        if self.openai_api_key:
            os.environ.setdefault("OPENAI_API_KEY", self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.export_provider_keys()
    return settings
