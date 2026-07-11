"""Resources layer API (Resources): CRUD across the four types, mcp_server
delegation to the existing store, and per-type health via the ``test`` endpoint."""

from __future__ import annotations

import httpx


async def test_create_and_list_model_provider(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/v1/resources/model_provider",
        json={"name": "openai", "config": {"provider": "openai", "models": ["gpt-4o"]}},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "openai"
    assert body["resource_type"] == "model_provider"

    listed = await client.get("/api/v1/resources/model_provider")
    assert listed.status_code == 200
    assert {r["name"] for r in listed.json()} == {"openai"}


async def test_unknown_type_is_422(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/resources/bogus")
    assert response.status_code == 422


async def test_create_and_delete(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/v1/resources/a2a_agent",
        json={"name": "peer", "config": {"url": "https://example.com"}},
    )
    assert created.status_code == 201, created.text

    deleted = await client.delete("/api/v1/resources/a2a_agent/peer")
    assert deleted.status_code == 204

    again = await client.delete("/api/v1/resources/a2a_agent/peer")
    assert again.status_code == 404
    assert again.json()["detail"] == "resource not found"


async def test_mcp_server_delegates_to_existing_store(client: httpx.AsyncClient) -> None:
    # created through the existing MCP-servers endpoint …
    created = await client.post(
        "/api/v1/mcp-servers",
        json={"name": "srv", "transport": "streamable_http", "config": {"url": "http://x/mcp"}},
    )
    assert created.status_code == 201, created.text
    # … and visible through the resources view (same underlying table)
    listed = await client.get("/api/v1/resources/mcp_server")
    assert listed.status_code == 200
    servers = {s["name"]: s for s in listed.json()}
    assert "srv" in servers
    assert servers["srv"]["resource_type"] == "mcp_server"
    assert servers["srv"]["config"]["transport"] == "streamable_http"


async def test_test_endpoint_model_provider_missing_key_is_e906(
    client: httpx.AsyncClient,
) -> None:
    await client.post(
        "/api/v1/resources/model_provider",
        json={"name": "oa", "config": {"provider": "openai"}},
    )
    report = await client.post("/api/v1/resources/model_provider/oa/test")
    assert report.status_code == 200
    body = report.json()
    assert body["ok"] is False
    assert body["code"] == "E906"


async def test_test_endpoint_knowledge_base_missing_collection_is_e903(
    client: httpx.AsyncClient,
) -> None:
    # the default `local` vector store connection is provisioned at boot
    await client.post(
        "/api/v1/resources/knowledge_base",
        json={"name": "kb", "config": {"vectorstore": "local", "collection": "nope"}},
    )
    report = await client.post("/api/v1/resources/knowledge_base/kb/test")
    assert report.status_code == 200
    body = report.json()
    assert body["ok"] is False
    assert body["code"] == "E903"


async def test_test_endpoint_missing_resource_is_404(client: httpx.AsyncClient) -> None:
    report = await client.post("/api/v1/resources/model_provider/ghost/test")
    assert report.status_code == 404
