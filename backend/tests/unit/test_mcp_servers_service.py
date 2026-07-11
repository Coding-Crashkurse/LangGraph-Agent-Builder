"""Unit tests for langgraph_agent_builder.services.mcp_servers (SPEC §8.3, §11.7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph_agent_builder.services.mcp_servers import McpServersService

if TYPE_CHECKING:
    from tests.unit.conftest import SqliteStack


async def test_upsert_inserts_then_get(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = McpServersService(sessions)
    created = await service.upsert(
        "search",
        "streamable_http",
        {"url": "https://mcp.example/x", "headers": {"Authorization": {"$secret": "mcp_token"}}},
    )
    assert created["name"] == "search"
    assert created["transport"] == "streamable_http"
    # secret refs are preserved verbatim (resolved only at connect time)
    assert created["config"]["headers"]["Authorization"] == {"$secret": "mcp_token"}

    fetched = await service.get("search")
    assert fetched is not None
    assert fetched["id"] == created["id"]


async def test_upsert_updates_existing_in_place(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = McpServersService(sessions)
    first = await service.upsert("srv", "streamable_http", {"url": "https://a"})
    second = await service.upsert("srv", "sse", {"url": "https://b"})

    assert second["id"] == first["id"]  # same row, updated
    assert second["transport"] == "sse"
    assert second["config"]["url"] == "https://b"

    listed = await service.list()
    assert len(listed) == 1


async def test_get_missing_returns_none(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = McpServersService(sessions)
    assert await service.get("nope") is None


async def test_delete_returns_true_then_false(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = McpServersService(sessions)
    await service.upsert("temp", "streamable_http", {"url": "https://x"})
    assert await service.delete("temp") is True
    assert await service.delete("temp") is False
    assert await service.list() == []
