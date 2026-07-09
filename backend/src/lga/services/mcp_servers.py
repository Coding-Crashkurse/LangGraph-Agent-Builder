"""Globally managed MCP servers (SPEC §8.3, §11.7) — picked by McpInput."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lga.db.models import McpServerRow


class McpServersService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list(self) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (await session.execute(select(McpServerRow))).scalars().all()
        return [self._info(r) for r in rows]

    async def get(self, name: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            row = (
                await session.execute(select(McpServerRow).where(McpServerRow.name == name))
            ).scalar_one_or_none()
        return self._info(row) if row else None

    async def upsert(self, name: str, transport: str, config: dict[str, Any]) -> dict[str, Any]:
        async with self._sessions() as session:
            row = (
                await session.execute(select(McpServerRow).where(McpServerRow.name == name))
            ).scalar_one_or_none()
            if row is None:
                row = McpServerRow(name=name)
                session.add(row)
            row.transport = transport
            row.config = config
            await session.commit()
            await session.refresh(row)
        return self._info(row)

    async def delete(self, name: str) -> bool:
        async with self._sessions() as session:
            result = await session.execute(delete(McpServerRow).where(McpServerRow.name == name))
            await session.commit()
            return bool(cast("CursorResult[Any]", result).rowcount)

    @staticmethod
    def _info(row: McpServerRow) -> dict[str, Any]:
        # secrets in config stay as {"$secret": name} refs — resolved at connect time
        return {
            "id": row.id,
            "name": row.name,
            "transport": row.transport,
            "config": row.config,
            "created_at": row.created_at.isoformat(),
        }
