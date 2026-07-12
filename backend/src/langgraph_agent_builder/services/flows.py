"""Builder-local draft storage (SPEC §3: ``CRUD /flows`` incl. layout).

Drafts are canonical FlowDefinition JSON objects — the persistence and
exchange format. Incomplete drafts (canvas in progress) are stored verbatim
in FlowDefinition shape; validation is advisory and never blocks a save.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from langgraph_agent_builder.errors import ConflictError, NotFoundError
from langgraph_agent_builder.serialization import canonical_definition_dict, require_name
from langgraph_agent_builder.services.db import FlowRow


@dataclass(frozen=True)
class StoredFlow:
    name: str
    owner: str
    definition: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _stored(row: FlowRow) -> StoredFlow:
    return StoredFlow(
        name=row.name,
        owner=row.owner,
        definition=dict(row.definition),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class FlowStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, raw: Mapping[str, Any], owner: str) -> StoredFlow:
        name = require_name(raw)
        row = FlowRow(name=name, owner=owner, definition=canonical_definition_dict(raw))
        async with self._sessions() as session:
            session.add(row)
            try:
                # the primary key is the race-safe guard against concurrent creates
                await session.commit()
            except IntegrityError as exc:
                raise ConflictError(f"flow {name!r} already exists") from exc
            await session.refresh(row)
        return _stored(row)

    async def save(self, name: str, raw: Mapping[str, Any], owner: str) -> StoredFlow:
        body_name = require_name(raw)
        if body_name != name:
            raise ConflictError(
                f"definition name {body_name!r} does not match flow {name!r}; "
                "export and re-import to rename"
            )
        async with self._sessions() as session:
            row = await session.get(FlowRow, name)
            if row is None or row.owner != owner:
                raise NotFoundError(f"flow {name!r} not found")
            row.definition = canonical_definition_dict(raw)
            await session.commit()
            await session.refresh(row)
        return _stored(row)

    async def upsert(self, raw: Mapping[str, Any], owner: str) -> tuple[StoredFlow, bool]:
        """Create-or-replace by name (import with overwrite). Returns (flow, created)."""
        name = require_name(raw)
        async with self._sessions() as session:
            row = await session.get(FlowRow, name)
            if row is not None and row.owner != owner:
                raise ConflictError(f"flow {name!r} belongs to another owner")
            created = row is None
            if row is None:
                row = FlowRow(name=name, owner=owner)
                session.add(row)
            row.definition = canonical_definition_dict(raw)
            await session.commit()
            await session.refresh(row)
        return _stored(row), created

    async def get(self, name: str, owner: str) -> StoredFlow:
        async with self._sessions() as session:
            row = await session.get(FlowRow, name)
        if row is None or row.owner != owner:
            raise NotFoundError(f"flow {name!r} not found")
        return _stored(row)

    async def list(self, owner: str) -> list[StoredFlow]:
        stmt = select(FlowRow).where(FlowRow.owner == owner).order_by(FlowRow.updated_at.desc())
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_stored(row) for row in rows]

    async def delete(self, name: str, owner: str) -> None:
        async with self._sessions() as session:
            row = await session.get(FlowRow, name)
            if row is None or row.owner != owner:
                raise NotFoundError(f"flow {name!r} not found")
            await session.delete(row)
            await session.commit()
