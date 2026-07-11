"""Unit tests for langgraph_agent_builder.services.vectorstores (SPEC §8b.3): connection CRUD,
secret/var resolution, provider building, health probing, and boot provisioning."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from langgraph_agent_builder.services.secrets import SecretsService
from langgraph_agent_builder.services.vectorstores import VectorStoreService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from langgraph_agent_builder.services.settings import Settings

SqliteStack = tuple["Settings", "async_sessionmaker[AsyncSession]"]


@pytest.fixture
def vs(sqlite_stack: SqliteStack) -> VectorStoreService:
    settings, sessions = sqlite_stack
    return VectorStoreService(settings, sessions, SecretsService(settings, sessions))


# --------------------------------------------------------------------- crud
async def test_upsert_creates_then_updates(vs: VectorStoreService) -> None:
    created = await vs.upsert("conn", "local", {"a": 1})
    assert created["name"] == "conn"
    assert created["backend"] == "local"
    assert created["config"] == {"a": 1}
    # second upsert mutates the existing row in place
    updated = await vs.upsert("conn", "local", {"a": 2}, managed=True)
    assert updated["id"] == created["id"]
    assert updated["config"] == {"a": 2}
    assert updated["managed"] is True
    assert len(await vs.list()) == 1


async def test_upsert_unknown_backend_raises(vs: VectorStoreService) -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        await vs.upsert("bad", "not-a-backend", {})


async def test_get_and_list(vs: VectorStoreService) -> None:
    await vs.upsert("a", "local", {})
    await vs.upsert("b", "local", {})
    assert {c["name"] for c in await vs.list()} == {"a", "b"}
    got_a = await vs.get("a")
    assert got_a is not None
    assert got_a["name"] == "a"
    assert await vs.get("missing") is None


async def test_delete(vs: VectorStoreService) -> None:
    await vs.upsert("gone", "local", {})
    assert await vs.delete("gone") is True
    assert await vs.get("gone") is None
    assert await vs.delete("gone") is False


# --------------------------------------------------------------------- secret/var resolution
async def test_resolve_params_secret_var_and_plain(
    sqlite_stack: SqliteStack, vs: VectorStoreService
) -> None:
    settings, sessions = sqlite_stack
    secrets = SecretsService(settings, sessions)
    await secrets.set("api_key", "sk-live", kind="credential")
    await secrets.set("region", "eu", kind="generic")
    service = VectorStoreService(settings, sessions, secrets)
    resolved = await service._resolve_params(
        {
            "url": "http://q",  # plain passthrough
            "key": {"$secret": "api_key"},  # credential ref
            "loc": {"$var": "region"},  # variable ref
            "missing": {"$secret": "absent"},  # unknown → empty string
        }
    )
    assert resolved == {"url": "http://q", "key": "sk-live", "loc": "eu", "missing": ""}


# --------------------------------------------------------------------- providers / health
async def test_provider_unknown_name_raises_keyerror(vs: VectorStoreService) -> None:
    with pytest.raises(KeyError):
        await vs.provider("ghost")


async def test_provider_builds_for_local(vs: VectorStoreService) -> None:
    await vs.upsert("local", "local", {})
    provider = await vs.provider("local")
    await provider.health()  # a healthy local backend returns without raising


async def test_health_ok_for_local(vs: VectorStoreService) -> None:
    await vs.upsert("local", "local", {})
    report = await vs.health("local")
    assert report["ok"] is True
    assert report["error"] is None
    assert report["collections"] == []


async def test_health_error_for_unknown_connection(vs: VectorStoreService) -> None:
    report = await vs.health("ghost")
    assert report["ok"] is False
    assert report["collections"] == []
    assert "ghost" in report["error"]


async def test_list_with_health_merges_info_and_probe(vs: VectorStoreService) -> None:
    await vs.upsert("local", "local", {})
    rows = await vs.list_with_health()
    assert len(rows) == 1
    assert rows[0]["name"] == "local"
    assert rows[0]["ok"] is True


# --------------------------------------------------------------------- provisioning
async def test_provision_creates_default_local(vs: VectorStoreService) -> None:
    await vs.provision()
    names = {c["name"] for c in await vs.list()}
    assert "local" in names
    got_local = await vs.get("local")
    assert got_local is not None
    assert got_local["managed"] is True
    # idempotent: a second provision does not duplicate
    await vs.provision()
    assert len([c for c in await vs.list() if c["name"] == "local"]) == 1


async def test_provision_reads_env_descriptors(
    sqlite_stack: SqliteStack, vs: VectorStoreService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_VECTORSTORE_EXTRA", '{"backend": "local", "path": "/tmp/x"}')
    monkeypatch.setenv("LAB_VECTORSTORE_UNKNOWN", '{"backend": "not-a-backend"}')
    await vs.provision()
    conns = {c["name"]: c for c in await vs.list()}
    assert conns["extra"]["backend"] == "local"
    assert conns["extra"]["config"] == {"path": "/tmp/x"}  # 'backend' key stripped
    assert "unknown" not in conns  # backend not installed → skipped
