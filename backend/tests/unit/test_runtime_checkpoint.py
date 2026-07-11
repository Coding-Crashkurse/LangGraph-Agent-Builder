"""Unit tests for runtime.checkpoint (CheckpointerFactory, sqlite tier + serde)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph_agent_builder.runtime.checkpoint import CheckpointerFactory
from langgraph_agent_builder.sdk.ports import Message

if TYPE_CHECKING:
    from langgraph_agent_builder.services.settings import Settings


async def test_sqlite_checkpointer_is_created_and_cached(sqlite_settings: Settings) -> None:
    factory = CheckpointerFactory(sqlite_settings)
    try:
        cp1 = await factory.get()
        assert cp1 is not None
        cp2 = await factory.get()
        assert cp2 is cp1  # process-wide singleton, built once
        assert (sqlite_settings.home / "checkpoints.db").exists()
    finally:
        await factory.aclose()


async def test_serde_roundtrips_lga_port_payload(sqlite_settings: Settings) -> None:
    factory = CheckpointerFactory(sqlite_settings)
    try:
        cp = await factory.get()
        msg = Message(role="assistant", content="checkpoint me", metadata={"k": 1})
        restored = cp.serde.loads_typed(cp.serde.dumps_typed(msg))
        assert isinstance(restored, Message)
        assert restored == msg
    finally:
        await factory.aclose()


async def test_aclose_resets_so_next_get_rebuilds(sqlite_settings: Settings) -> None:
    factory = CheckpointerFactory(sqlite_settings)
    cp1 = await factory.get()
    await factory.aclose()
    cp2 = await factory.get()
    try:
        assert cp2 is not cp1  # closed → a fresh checkpointer is constructed
    finally:
        await factory.aclose()
