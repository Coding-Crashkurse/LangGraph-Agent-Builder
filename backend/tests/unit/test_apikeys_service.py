"""Unit tests for langgraph_agent_builder.services.apikeys (SPEC §10.4).

Exercises scope validation, revocation, wildcard scope, and usage tracking on
a real migrated SQLite database via the `sqlite_stack` fixture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from langgraph_agent_builder.services.apikeys import ApiKeyService

if TYPE_CHECKING:
    from tests.unit.conftest import SqliteStack


async def test_create_rejects_unknown_scope(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = ApiKeyService(sessions)
    with pytest.raises(ValueError, match="unknown scope"):
        await service.create(["not:a:scope"])


async def test_create_returns_prefixed_key_and_info(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = ApiKeyService(sessions)
    key, info = await service.create(["a2a:invoke"], name="ci")
    assert key.startswith("lab_sk_")
    assert info["prefix"] == key[:14]
    assert info["name"] == "ci"
    assert info["scopes"] == ["a2a:invoke"]
    assert info["revoked"] is False
    assert info["total_uses"] == 0
    assert info["last_used_at"] is None


async def test_verify_scope_and_wildcard(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = ApiKeyService(sessions)
    scoped_key, _ = await service.create(["a2a:invoke"])
    wildcard_key, _ = await service.create(["studio:*"])

    assert await service.verify(scoped_key, "a2a:invoke") is True
    # a key without the requested scope is denied
    assert await service.verify(scoped_key, "mcp:invoke") is False
    # studio:* satisfies any scope
    assert await service.verify(wildcard_key, "mcp:invoke") is True


async def test_verify_empty_and_unknown_key(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = ApiKeyService(sessions)
    assert await service.verify("", "a2a:invoke") is False
    assert await service.verify("lab_sk_nope", "a2a:invoke") is False


async def test_revoke_denies_future_verification(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = ApiKeyService(sessions)
    key, info = await service.create(["a2a:invoke"])
    assert await service.verify(key, "a2a:invoke") is True

    assert await service.revoke(info["id"]) is True
    assert await service.verify(key, "a2a:invoke") is False

    listed = {row["id"]: row for row in await service.list()}
    assert listed[info["id"]]["revoked"] is True


async def test_revoke_missing_key_returns_false(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = ApiKeyService(sessions)
    assert await service.revoke("00000000-0000-0000-0000-000000000000") is False


async def test_usage_tracking_increments(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = ApiKeyService(sessions)
    key, info = await service.create(["a2a:invoke"])
    await service.verify(key, "a2a:invoke")
    await service.verify(key, "a2a:invoke")

    listed = {row["id"]: row for row in await service.list()}
    row = listed[info["id"]]
    assert row["total_uses"] == 2
    assert row["last_used_at"] is not None


async def test_usage_tracking_disabled(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = ApiKeyService(sessions, track_usage=False)
    key, info = await service.create(["a2a:invoke"])
    assert await service.verify(key, "a2a:invoke") is True

    listed = {row["id"]: row for row in await service.list()}
    row = listed[info["id"]]
    assert row["total_uses"] == 0
    assert row["last_used_at"] is None


async def test_verify_denied_key_not_tracked(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    service = ApiKeyService(sessions)
    key, info = await service.create(["a2a:invoke"])
    # wrong scope -> denied -> usage must NOT be recorded
    assert await service.verify(key, "mcp:invoke") is False

    listed = {row["id"]: row for row in await service.list()}
    row = listed[info["id"]]
    assert row["total_uses"] == 0
    assert row["last_used_at"] is None
