"""Async persistence for builder-local drafts (one table, SQLite by default)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from langgraph_agent_builder.services.settings import Settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class FlowRow(Base):
    """One builder-local working copy: canonical FlowDefinition JSON incl. layout."""

    __tablename__ = "flows"

    name: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(sa.String(255), default="anonymous")
    definition: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.async_database_url)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
