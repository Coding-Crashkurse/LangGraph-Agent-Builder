"""Programmatic Alembic runner — migrations ship inside the wheel (SPEC §2.6)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from langgraph_agent_builder.services.settings import Settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def sync_url(settings: Settings) -> str:
    """Async SQLAlchemy URL → sync driver URL for Alembic."""
    url = settings.async_database_url
    url = url.replace("sqlite+aiosqlite://", "sqlite://")
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    return url


def build_config(settings: Settings) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", sync_url(settings))
    return cfg


def upgrade(settings: Settings, revision: str = "head") -> None:
    if settings.is_sqlite:
        settings.ensure_dirs()
        settings.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(build_config(settings), revision)


def offline_sql(settings: Settings, revision: str = "head") -> None:
    command.upgrade(build_config(settings), revision, sql=True)


async def upgrade_async(settings: Settings, revision: str = "head") -> None:
    """Run Alembic in a worker thread (it is sync) — used by app lifespan."""
    await asyncio.to_thread(upgrade, settings, revision)
