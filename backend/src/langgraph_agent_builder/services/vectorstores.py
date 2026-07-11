"""Named vector store connections (SPEC §8b.3) — server-managed, secret-safe.

FlowSpecs reference connections *by name* (``{"$vectorstore": "prod"}``), never
by credentials, so flows stay portable. A default ``local`` connection is
auto-created on first boot; ``LAB_VECTORSTORE_<NAME>`` descriptors provision
connections at boot for deploy parity.
"""

from __future__ import annotations

import asyncio
import builtins
import json
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from langgraph_agent_builder.db.models import VectorStoreConnectionRow
from langgraph_agent_builder.services.secrets import SecretsService
from langgraph_agent_builder.services.settings import Settings
from langgraph_agent_builder.vectorstores import (
    BACKEND_EXTRAS,
    CollectionInfo,
    CollectionMissing,
    DimensionMismatch,
    VectorStoreProvider,
    build_provider,
)


class VectorStoreService:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        secrets: SecretsService,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._secrets = secrets
        # providers are cached per connection name and rebuilt only when the
        # resolved config changes (or the connection is upserted/deleted) —
        # backends keep a live client/pool, so one instance per connection
        self._providers: dict[str, tuple[str, VectorStoreProvider]] = {}
        self._providers_lock = asyncio.Lock()

    # ------------------------------------------------------------------ crud
    async def list(self) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (await session.execute(select(VectorStoreConnectionRow))).scalars().all()
        return [self._info(r) for r in rows]

    async def get(self, name: str) -> dict[str, Any] | None:
        row = await self._row(name)
        return self._info(row) if row else None

    async def _row(self, name: str) -> VectorStoreConnectionRow | None:
        async with self._sessions() as session:
            return (
                await session.execute(
                    select(VectorStoreConnectionRow).where(VectorStoreConnectionRow.name == name)
                )
            ).scalar_one_or_none()

    async def upsert(
        self, name: str, backend: str, config: dict[str, Any], *, managed: bool = False
    ) -> dict[str, Any]:
        if backend not in BACKEND_EXTRAS:
            raise ValueError(f"unknown backend {backend!r}")
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(VectorStoreConnectionRow).where(VectorStoreConnectionRow.name == name)
                )
            ).scalar_one_or_none()
            if row is None:
                row = VectorStoreConnectionRow(name=name)
                session.add(row)
            row.backend = backend
            row.config = config
            row.managed = managed
            await session.commit()
            await session.refresh(row)
        await self._invalidate(name)
        return self._info(row)

    async def delete(self, name: str) -> bool:
        async with self._sessions() as session:
            result = await session.execute(
                delete(VectorStoreConnectionRow).where(VectorStoreConnectionRow.name == name)
            )
            await session.commit()
        await self._invalidate(name)
        return bool(cast("CursorResult[Any]", result).rowcount)

    # ------------------------------------------------------------------ providers
    async def provider(self, name: str) -> VectorStoreProvider:
        """Live provider for a named connection, resolving ``$secret`` refs.

        Cached per connection so backends reuse their client/pool instead of
        reconnecting per call; a changed config (connection CRUD or rotated
        secret) closes the old provider and builds a fresh one.
        """
        row = await self._row(name)
        if row is None:
            raise KeyError(name)
        params = await self._resolve_params(dict(row.config or {}))
        fingerprint = f"{row.backend}:{json.dumps(params, sort_keys=True, default=str)}"
        async with self._providers_lock:
            cached = self._providers.get(name)
            if cached is not None and cached[0] == fingerprint:
                return cached[1]
            if cached is not None:
                await self._aclose_provider(cached[1])
            provider = build_provider(row.backend, name, params, home=self._settings.home)
            self._providers[name] = (fingerprint, provider)
            return provider

    async def _invalidate(self, name: str) -> None:
        async with self._providers_lock:
            cached = self._providers.pop(name, None)
        if cached is not None:
            await self._aclose_provider(cached[1])

    @staticmethod
    async def _aclose_provider(provider: VectorStoreProvider) -> None:
        # aclose is deliberately not part of the SPEC §8b.1 protocol — built-in
        # providers have it, custom backends may not
        closer = getattr(provider, "aclose", None)
        if closer is not None:
            try:
                await closer()
            except Exception:  # pragma: no cover - best-effort teardown
                pass

    async def aclose(self) -> None:
        """Close every cached provider (app shutdown / test teardown)."""
        async with self._providers_lock:
            cached, self._providers = list(self._providers.values()), {}
        for _, provider in cached:
            await self._aclose_provider(provider)

    async def check_collection(
        self, name: str, collection: str, dim: int | None = None
    ) -> CollectionInfo:
        """Deep-validate support (SPEC §8b.4): E902/E903/E904 fodder.

        Raises ``VectorStoreError`` (→ E902) when the backend is unreachable,
        :class:`CollectionMissing` (→ E903) when the collection is absent, and
        :class:`DimensionMismatch` (→ E904) when ``dim`` is given and disagrees
        with the collection. Backends that cannot report a dim (0) are skipped
        rather than failed.
        """
        provider = await self.provider(name)
        for info in await provider.list_collections():
            if info.name == collection:
                if dim is not None and info.dim and info.dim != dim:
                    raise DimensionMismatch(provider.backend, info.dim, dim)
                return info
        raise CollectionMissing(provider.backend, collection)

    async def _resolve_params(self, params: dict[str, Any]) -> dict[str, Any]:
        variables, secrets = await self._secrets.snapshot()
        out: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, dict) and "$secret" in value:
                out[key] = secrets.get(value["$secret"], "")
            elif isinstance(value, dict) and "$var" in value:
                out[key] = variables.get(value["$var"], "")
            else:
                out[key] = value
        return out

    async def health(self, name: str) -> dict[str, Any]:
        try:
            provider = await self.provider(name)
            await provider.health()
            collections = await provider.list_collections()
            return {
                "ok": True,
                "collections": [c.model_dump() for c in collections],
                "error": None,
            }
        except Exception as exc:
            return {"ok": False, "collections": [], "error": str(exc)}

    async def list_with_health(self) -> builtins.list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for info in await self.list():
            health = await self.health(info["name"])
            out.append({**info, **health})
        return out

    # ------------------------------------------------------------------ boot provisioning
    async def provision(self) -> None:
        """Auto-create the ``local`` default + env-declared connections (§8b.3)."""
        existing = {c["name"] for c in await self.list()}
        if "local" not in existing:
            await self.upsert("local", "local", {}, managed=True)
        for name, descriptor in self._settings.vectorstore_env_connections().items():
            backend = str(descriptor.get("backend", "local"))
            params = {k: v for k, v in descriptor.items() if k != "backend"}
            if backend in BACKEND_EXTRAS:
                await self.upsert(name, backend, params, managed=True)

    @staticmethod
    def _info(row: VectorStoreConnectionRow) -> dict[str, Any]:
        # credential params stay as {"$secret": name} refs — never returned raw
        return {
            "id": row.id,
            "name": row.name,
            "backend": row.backend,
            "config": row.config,
            "managed": row.managed,
            "created_at": row.created_at.isoformat(),
        }
