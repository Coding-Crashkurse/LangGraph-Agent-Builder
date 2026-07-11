"""Unit tests for langgraph_agent_builder.services.resources (Resources layer):
CRUD across the four resource types, mcp_server delegation to the existing
store, secret-safe ``_resolve_params`` + ``_info`` masking, version-aware
``names_with_types`` lookup, and per-type health probes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from langgraph_agent_builder.services.mcp_servers import McpServersService
from langgraph_agent_builder.services.resources import ResourcesService, _resource_key_type
from langgraph_agent_builder.services.secrets import SecretsService
from langgraph_agent_builder.services.vectorstores import VectorStoreService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from langgraph_agent_builder.services.settings import Settings

SqliteStack = tuple["Settings", "async_sessionmaker[AsyncSession]"]


@pytest.fixture
def resources(sqlite_stack: SqliteStack) -> ResourcesService:
    settings, sessions = sqlite_stack
    secrets = SecretsService(settings, sessions)
    return ResourcesService(
        settings,
        sessions,
        secrets,
        McpServersService(sessions),
        VectorStoreService(settings, sessions, secrets),
    )


# --------------------------------------------------------------------- crud
async def test_upsert_creates_then_updates(resources: ResourcesService) -> None:
    created = await resources.upsert("model_provider", "openai", {"provider": "openai"})
    assert created["name"] == "openai"
    assert created["resource_type"] == "model_provider"
    assert created["config"] == {"provider": "openai"}
    updated = await resources.upsert(
        "model_provider", "openai", {"provider": "openai", "models": ["gpt-4o"]}
    )
    assert updated["id"] == created["id"]  # mutated in place
    assert updated["config"]["models"] == ["gpt-4o"]
    assert len(await resources.list("model_provider")) == 1


async def test_unknown_type_raises(resources: ResourcesService) -> None:
    with pytest.raises(ValueError, match="unknown resource type"):
        await resources.list("bogus")


async def test_get_and_list(resources: ResourcesService) -> None:
    await resources.upsert("knowledge_base", "kb1", {"vectorstore": "local"})
    await resources.upsert("a2a_agent", "peer", {"url": "https://example.com"})
    assert {c["name"] for c in await resources.list("knowledge_base")} == {"kb1"}
    got = await resources.get("knowledge_base", "kb1")
    assert got is not None
    assert got["name"] == "kb1"
    assert await resources.get("knowledge_base", "missing") is None


async def test_delete(resources: ResourcesService) -> None:
    await resources.upsert("model_provider", "gone", {"provider": "fake"})
    assert await resources.delete("model_provider", "gone") is True
    assert await resources.get("model_provider", "gone") is None
    assert await resources.delete("model_provider", "gone") is False


# --------------------------------------------------------------------- mcp delegation
async def test_mcp_server_delegates_to_existing_store(
    resources: ResourcesService, sqlite_stack: SqliteStack
) -> None:
    _settings, sessions = sqlite_stack
    await resources.upsert(
        "mcp_server", "srv", {"transport": "streamable_http", "url": "http://localhost:9000/mcp"}
    )
    # stored in the shared mcp_servers table, not a duplicate resources table
    shared = await McpServersService(sessions).get("srv")
    assert shared is not None
    assert shared["transport"] == "streamable_http"
    assert shared["config"] == {"url": "http://localhost:9000/mcp"}  # transport folded out
    listed = {c["name"]: c for c in await resources.list("mcp_server")}
    assert listed["srv"]["resource_type"] == "mcp_server"
    assert listed["srv"]["config"]["transport"] == "streamable_http"
    assert await resources.delete("mcp_server", "srv") is True


# --------------------------------------------------------------------- secret masking
async def test_resolve_params_secret_var_and_plain(
    resources: ResourcesService, sqlite_stack: SqliteStack
) -> None:
    settings, sessions = sqlite_stack
    secrets = SecretsService(settings, sessions)
    await secrets.set("api_key", "sk-live", kind="credential")
    await secrets.set("region", "eu", kind="generic")
    resolved = await resources._resolve_params(
        {
            "url": "http://q",
            "api_key": {"$secret": "api_key"},
            "loc": {"$var": "region"},
            "missing": {"$secret": "absent"},
        }
    )
    assert resolved == {"url": "http://q", "api_key": "sk-live", "loc": "eu", "missing": ""}


async def test_info_never_leaks_secret(resources: ResourcesService) -> None:
    created = await resources.upsert(
        "model_provider", "sec", {"provider": "openai", "api_key": {"$secret": "K"}}
    )
    # the credential stays a {"$secret": ...} ref — never resolved into _info
    assert created["config"]["api_key"] == {"$secret": "K"}


# --------------------------------------------------------------------- resolver lookup
async def test_names_with_types_unions_and_versions(resources: ResourcesService) -> None:
    await resources.upsert("model_provider", "gpt", {"provider": "openai"})
    await resources.upsert("mcp_server", "srv", {"url": "http://x/mcp"})
    lookup = await resources.names_with_types()
    assert set(lookup) == {"gpt", "srv"}
    assert _resource_key_type(lookup["gpt"]) == "model_provider"
    assert _resource_key_type(lookup["srv"]) == "mcp_server"
    # editing config changes the version token (→ compile cache invalidation)
    before = lookup["gpt"]
    await resources.upsert("model_provider", "gpt", {"provider": "openai", "models": ["x"]})
    after = (await resources.names_with_types())["gpt"]
    assert after != before
    assert _resource_key_type(after) == "model_provider"


# --------------------------------------------------------------------- health
async def test_health_model_provider_ok_for_fake(resources: ResourcesService) -> None:
    await resources.upsert("model_provider", "f", {"provider": "fake"})
    report = await resources.health("model_provider", "f")
    assert report["ok"] is True


async def test_health_model_provider_missing_key_is_e906(resources: ResourcesService) -> None:
    await resources.upsert("model_provider", "oa", {"provider": "openai"})
    report = await resources.health("model_provider", "oa")
    assert report["ok"] is False
    assert report["code"] == "E906"


async def test_health_knowledge_base_missing_collection_is_e903(
    resources: ResourcesService,
) -> None:
    await resources._vectorstores.upsert("local", "local", {})
    await resources.upsert("knowledge_base", "kb", {"vectorstore": "local", "collection": "nope"})
    report = await resources.health("knowledge_base", "kb")
    assert report["ok"] is False
    assert report["code"] == "E903"


async def test_health_a2a_agent_private_url_is_e907(resources: ResourcesService) -> None:
    # localhost is a private address → SSRF guard rejects before any egress
    await resources.upsert("a2a_agent", "peer", {"url": "http://localhost:9999"})
    report = await resources.health("a2a_agent", "peer")
    assert report["ok"] is False
    assert report["code"] == "E907"


async def test_health_missing_resource(resources: ResourcesService) -> None:
    report = await resources.health("model_provider", "ghost")
    assert report["ok"] is False


# --------------------------------------------------------------------- provisioning
async def test_provision_reads_env_descriptors(
    resources: ResourcesService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "LAB_RESOURCE_GPT", '{"type": "model_provider", "config": {"provider": "openai"}}'
    )
    monkeypatch.setenv("LAB_RESOURCE_BAD", '{"type": "not-a-type", "config": {}}')
    await resources.provision()
    got = await resources.get("model_provider", "gpt")
    assert got is not None
    assert got["config"] == {"provider": "openai"}
    assert await resources.get("model_provider", "bad") is None  # unknown type skipped
