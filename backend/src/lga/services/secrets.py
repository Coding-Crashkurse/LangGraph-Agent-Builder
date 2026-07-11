"""Global variables & secrets (SPEC §10.3).

Kinds: `generic` (plain) | `credential` (Fernet-encrypted at rest, write-only
through the API). Env promotion: LGA_VAR_<NAME> / LGA_CRED_<NAME>.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any, cast

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lga.db.models import GlobalVariableRow
from lga.services.settings import Settings

if TYPE_CHECKING:
    from lga.db.models import FlowRow

ENV_VAR_PREFIX = "LGA_VAR_"
ENV_CRED_PREFIX = "LGA_CRED_"


def _spec_refs(value: Any) -> Iterator[str]:
    """Yield every `{"$var": name}` / `{"$secret": name}` reference in a spec (§10.3)."""
    if isinstance(value, dict):
        for key in ("$var", "$secret"):
            ref = value.get(key)
            if isinstance(ref, str):
                yield ref
        for child in value.values():
            yield from _spec_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _spec_refs(child)


def variable_usage(flows: Iterable[FlowRow]) -> dict[str, list[str]]:
    """Variable name → slugs of flows referencing it — feeds `in_use_by` (§10.3)."""
    usage: dict[str, set[str]] = {}
    for flow in flows:
        for name in _spec_refs(flow.spec or {}):
            usage.setdefault(name, set()).add(flow.slug)
    return {name: sorted(slugs) for name, slugs in usage.items()}


class SecretsService:
    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._settings = settings
        self._sessions = sessions
        self._fernet = Fernet(settings.resolve_secret_key().encode())

    # ---------------------------------------------------------------- crud
    async def set(self, name: str, value: str, kind: str = "generic") -> None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(GlobalVariableRow).where(GlobalVariableRow.name == name)
                )
            ).scalar_one_or_none()
            if row is None:
                row = GlobalVariableRow(name=name, kind=kind)
                session.add(row)
            row.kind = kind
            if kind == "credential":
                row.value_encrypted = self._fernet.encrypt(value.encode()).decode()
                row.value_plain = None
            else:
                row.value_plain = value
                row.value_encrypted = None
            await session.commit()

    async def delete(self, name: str) -> bool:
        async with self._sessions() as session:
            result = await session.execute(
                delete(GlobalVariableRow).where(GlobalVariableRow.name == name)
            )
            await session.commit()
            return bool(cast("CursorResult[Any]", result).rowcount)

    async def list(self, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        """Metadata only — credential values are never returned (write-only)."""
        stmt = select(GlobalVariableRow).order_by(GlobalVariableRow.name).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "name": r.name,
                "kind": r.kind,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]

    # ---------------------------------------------------------------- resolution
    def _decrypt(self, row: GlobalVariableRow) -> str | None:
        if row.kind == "credential":
            if not row.value_encrypted:
                return None
            try:
                return self._fernet.decrypt(row.value_encrypted.encode()).decode()
            except InvalidToken:
                return None
        return row.value_plain

    async def snapshot(self) -> tuple[dict[str, str], dict[str, str]]:
        """(vars, secrets) with env promotion applied — feeds the compiler."""
        variables: dict[str, str] = {}
        secrets: dict[str, str] = {}
        async with self._sessions() as session:
            rows = (await session.execute(select(GlobalVariableRow))).scalars().all()
        for row in rows:
            value = self._decrypt(row)
            if value is None:
                continue
            (secrets if row.kind == "credential" else variables)[row.name] = value
        for key, value in os.environ.items():
            if key.startswith(ENV_VAR_PREFIX):
                variables.setdefault(key.removeprefix(ENV_VAR_PREFIX).lower(), value)
                variables.setdefault(key.removeprefix(ENV_VAR_PREFIX), value)
            elif key.startswith(ENV_CRED_PREFIX):
                secrets.setdefault(key.removeprefix(ENV_CRED_PREFIX).lower(), value)
                secrets.setdefault(key.removeprefix(ENV_CRED_PREFIX), value)
        return variables, secrets


class SnapshotVariablesProvider:
    """compiler.resolve.VariablesProvider over a pre-fetched snapshot."""

    def __init__(self, variables: dict[str, str], secrets: dict[str, str]) -> None:
        self._vars = variables
        self._secrets = secrets

    def get_var(self, name: str) -> str | None:
        return self._vars.get(name) or self._vars.get(name.lower())

    def get_secret(self, name: str) -> str | None:
        return self._secrets.get(name) or self._secrets.get(name.lower())

    def has_var(self, name: str) -> bool:
        return self.get_var(name) is not None

    def has_secret(self, name: str) -> bool:
        return self.get_secret(name) is not None
