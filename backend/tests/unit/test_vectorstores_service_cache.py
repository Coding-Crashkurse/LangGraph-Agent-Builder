"""Unit tests for the VectorStoreService provider lifecycle (SPEC §8b.3/§8b.4):
per-connection provider caching, invalidation on connection CRUD and secret
rotation, ``aclose`` teardown, and the deep-validate ``check_collection`` probe
(E903/E904 fodder — mapped by ``services/orchestrator.py``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from langgraph_agent_builder.services.secrets import SecretsService
from langgraph_agent_builder.services.vectorstores import VectorStoreService
from langgraph_agent_builder.vectorstores.base import CollectionMissing, DimensionMismatch
from langgraph_agent_builder.vectorstores.local import LocalVectorStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from langgraph_agent_builder.services.settings import Settings

SqliteStack = tuple["Settings", "async_sessionmaker[AsyncSession]"]

DIM = 8


@pytest.fixture
def vs(sqlite_stack: SqliteStack) -> VectorStoreService:
    settings, sessions = sqlite_stack
    return VectorStoreService(settings, sessions, SecretsService(settings, sessions))


# --------------------------------------------------------------------- caching
async def test_provider_is_cached_per_connection(vs: VectorStoreService) -> None:
    await vs.upsert("conn", "local", {})
    first = await vs.provider("conn")
    # cache hit → the backend keeps one live client/pool instead of
    # reconnecting (and re-running DDL) per call
    assert await vs.provider("conn") is first


async def test_upsert_invalidates_and_closes_cached_provider(vs: VectorStoreService) -> None:
    await vs.upsert("conn", "local", {})
    first = await vs.provider("conn")
    assert isinstance(first, LocalVectorStore)
    await first.health()  # open the lazy connection so the close is observable
    assert first._db is not None
    await vs.upsert("conn", "local", {"changed": True})
    assert await vs.provider("conn") is not first
    assert first._db is None  # old provider was aclosed, not leaked


async def test_delete_invalidates_cached_provider(vs: VectorStoreService) -> None:
    await vs.upsert("conn", "local", {})
    first = await vs.provider("conn")
    await vs.delete("conn")
    with pytest.raises(KeyError):
        await vs.provider("conn")
    await vs.upsert("conn", "local", {})
    assert await vs.provider("conn") is not first


async def test_rotated_secret_rebuilds_provider_without_crud(
    sqlite_stack: SqliteStack,
) -> None:
    settings, sessions = sqlite_stack
    secrets = SecretsService(settings, sessions)
    vs = VectorStoreService(settings, sessions, secrets)
    await secrets.set("token", "one", kind="credential")
    await vs.upsert("conn", "local", {"api_key": {"$secret": "token"}})
    first = await vs.provider("conn")
    assert await vs.provider("conn") is first  # unchanged secret → cache hit
    await secrets.set("token", "two", kind="credential")
    assert await vs.provider("conn") is not first  # resolved fingerprint changed


async def test_service_aclose_closes_and_clears_cache(vs: VectorStoreService) -> None:
    await vs.upsert("conn", "local", {})
    first = await vs.provider("conn")
    assert isinstance(first, LocalVectorStore)
    await first.health()
    await vs.aclose()
    assert first._db is None
    assert await vs.provider("conn") is not first


# --------------------------------------------------------------------- deep validate
async def test_check_collection_returns_info(vs: VectorStoreService) -> None:
    await vs.upsert("conn", "local", {})
    provider = await vs.provider("conn")
    await provider.ensure_collection("kb", DIM)
    info = await vs.check_collection("conn", "kb", dim=DIM)
    assert info.name == "kb"
    assert info.dim == DIM


async def test_check_collection_missing_raises_e903_fodder(vs: VectorStoreService) -> None:
    await vs.upsert("conn", "local", {})
    with pytest.raises(CollectionMissing):
        await vs.check_collection("conn", "ghost")


async def test_check_collection_dim_mismatch_raises_e904_fodder(vs: VectorStoreService) -> None:
    await vs.upsert("conn", "local", {})
    provider = await vs.provider("conn")
    await provider.ensure_collection("kb", DIM)
    with pytest.raises(DimensionMismatch):
        await vs.check_collection("conn", "kb", dim=DIM + 1)


async def test_check_collection_skips_dim_when_not_given(vs: VectorStoreService) -> None:
    await vs.upsert("conn", "local", {})
    provider = await vs.provider("conn")
    await provider.ensure_collection("kb", DIM)
    info = await vs.check_collection("conn", "kb")
    assert info.dim == DIM
