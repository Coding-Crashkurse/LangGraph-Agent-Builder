"""Shared fixtures for unit-tier service tests.

`sqlite_stack` yields a migrated SQLite database plus a sessionmaker so each
service can be constructed directly (no full FastAPI app / lifespan needed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from langgraph_agent_builder.services.settings import Settings

SqliteStack = tuple["Settings", "async_sessionmaker[AsyncSession]"]


@pytest.fixture
async def sqlite_stack(sqlite_settings: Settings) -> AsyncIterator[SqliteStack]:
    from langgraph_agent_builder.db.migrate import upgrade_async
    from langgraph_agent_builder.services.db import create_engine, create_sessionmaker

    await upgrade_async(sqlite_settings)
    engine = create_engine(sqlite_settings)
    sessions = create_sessionmaker(engine)
    yield sqlite_settings, sessions
    await engine.dispose()
