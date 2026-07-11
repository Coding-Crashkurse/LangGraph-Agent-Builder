"""Async engine/session factory, tier-agnostic (SPEC §2.8)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from langgraph_agent_builder.services.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    url = settings.async_database_url
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if settings.is_sqlite:
        settings.ensure_dirs()
        settings.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
        # sqlite has no pooling concerns; pre_ping is pointless there
        kwargs = {"connect_args": {"timeout": 30}}
    engine = create_async_engine(url, **kwargs)
    if settings.is_sqlite:
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn: Any, _record: object) -> None:  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
