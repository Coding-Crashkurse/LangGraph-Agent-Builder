"""CheckpointerFactory — one interface, tier-selected backend (SPEC §6.3, §2.8)."""

from __future__ import annotations

from contextlib import AsyncExitStack
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

    async def get(self) -> Any:
        if self._checkpointer is None:
            if self._settings.is_postgres:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                self._checkpointer = await self._stack.enter_async_context(
                    AsyncPostgresSaver.from_conn_string(self._settings.psycopg_dsn)
                )
                self._checkpointer.serde = _serde()
                await self._checkpointer.setup()
            else:
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                self._settings.ensure_dirs()
                path = self._settings.home / "checkpoints.db"
                self._checkpointer = await self._stack.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(str(path))
                )
                self._checkpointer.serde = _serde()
                await self._checkpointer.setup()
        return self._checkpointer

    async def aclose(self) -> None:
        await self._stack.aclose()
        self._checkpointer = None
