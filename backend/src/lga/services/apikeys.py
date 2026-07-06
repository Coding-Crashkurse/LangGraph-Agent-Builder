"""API keys (SPEC §10.4): `lga_sk_…`, stored hashed, scoped, revocable."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lga.db.models import ApiKeyRow

SCOPES = ("studio:*", "a2a:invoke", "mcp:invoke", "webhook:invoke")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class ApiKeyService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], track_usage: bool = True
    ) -> None:
        self._sessions = sessions
        self._track_usage = track_usage

    async def create(self, scopes: list[str], name: str = "") -> tuple[str, dict[str, Any]]:
        """Returns (plaintext_key, row_info). The plaintext is shown exactly once."""
        for scope in scopes:
            if scope not in SCOPES:
                raise ValueError(f"unknown scope {scope!r} (valid: {', '.join(SCOPES)})")
        key = "lga_sk_" + secrets.token_urlsafe(32)
        row = ApiKeyRow(name=name, key_hash=_hash(key), prefix=key[:14], scopes=scopes)
        async with self._sessions() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return key, self._info(row)

    async def list(self) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (await session.execute(select(ApiKeyRow))).scalars().all()
        return [self._info(r) for r in rows]

    async def revoke(self, key_id: str) -> bool:
        async with self._sessions() as session:
            row = await session.get(ApiKeyRow, key_id)
            if row is None:
                return False
            row.revoked_at = datetime.now(UTC)
            await session.commit()
            return True

    async def verify(self, key: str, scope: str) -> bool:
        """True iff key exists, is not revoked, and carries the scope (or studio:*)."""
        if not key:
            return False
        async with self._sessions() as session:
            row = (
                await session.execute(select(ApiKeyRow).where(ApiKeyRow.key_hash == _hash(key)))
            ).scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                return False
            allowed = "studio:*" in (row.scopes or []) or scope in (row.scopes or [])
            if allowed and self._track_usage:
                row.last_used_at = datetime.now(UTC)
                row.total_uses = (row.total_uses or 0) + 1
                await session.commit()
            return allowed

    @staticmethod
    def _info(row: ApiKeyRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "prefix": row.prefix,
            "scopes": row.scopes,
            "created_at": row.created_at.isoformat(),
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "total_uses": row.total_uses,
            "revoked": row.revoked_at is not None,
        }
