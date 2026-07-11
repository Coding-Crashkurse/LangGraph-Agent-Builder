"""CheckpointerFactory — one interface, tier-selected backend (SPEC §6.3, §2.8)."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import TYPE_CHECKING, Any

from lga.services.settings import Settings

if TYPE_CHECKING:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def _serde() -> JsonPlusSerializer:
    """Serializer that trusts our own port payload types in checkpoints."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer(
        allowed_msgpack_modules=(
            ("lga.sdk.ports", "Message"),
            ("lga.sdk.ports", "Document"),
            ("lga.sdk.ports", "FileRef"),
        )
    )


class CheckpointerFactory:
    """Owns the process-wide checkpointer; runtime code never branches on backend."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stack = AsyncExitStack()
        self._checkpointer: Any = None
        self._lock = asyncio.Lock()

    async def get(self) -> Any:
        # double-checked lock: concurrent first calls (boot remount + webhook,
        # parallel A2A tasks) must not open two savers against one database
        if self._checkpointer is None:
            async with self._lock:
                if self._checkpointer is None:
                    self._checkpointer = await self._build()
        return self._checkpointer

    async def _build(self) -> Any:
        ctx: AbstractAsyncContextManager[Any]
        if self._settings.is_postgres:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            ctx = AsyncPostgresSaver.from_conn_string(self._settings.psycopg_dsn)
        else:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            self._settings.ensure_dirs()
            ctx = AsyncSqliteSaver.from_conn_string(str(self._settings.home / "checkpoints.db"))
        saver: Any = await self._stack.enter_async_context(ctx)
        saver.serde = _serde()
        await saver.setup()
        return saver

    async def aclose(self) -> None:
        await self._stack.aclose()
        self._checkpointer = None
