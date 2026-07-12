"""GET /resources — runtime proxy, names + kinds only (SPEC §2.6, §3)."""

from __future__ import annotations

import respx
from httpx import AsyncClient, Response

from tests.conftest import RUNTIME_URL

_RUNTIME_RESOURCES = [
    {
        "kind": "model_provider",
        "name": "default-llm",
        "display_name": "Default LLM",
        "base_url": "http://gateway.test/llm",
        "api_key_secret": "•••",
        "default_model": "gpt-5-mini",
    },
    {
        "kind": "pgvector",
        "name": "kb-support",
        "display_name": "Support KB",
        "url": "",
        "embedding": {"resource": "default-llm", "model": "text-emb", "dimension": 1536},
    },
    {
        "kind": "mcp_server",
        "name": "weather-tools",
        "display_name": "Weather Tools",
        "url": "http://gateway.test/mcp/weather",
    },
]


@respx.mock
async def test_resources_proxied_names_and_kinds_only(runtime_client: AsyncClient) -> None:
    respx.get(f"{RUNTIME_URL}/api/v1/resources").mock(
        return_value=Response(200, json=_RUNTIME_RESOURCES)
    )
    resp = await runtime_client.get("/api/v1/resources")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["name"] for r in body] == ["default-llm", "kb-support", "weather-tools"]
    assert [r["group"] for r in body] == ["model_provider", "vector_db", "mcp_server"]
    # no credentials, URLs or secrets ever reach the frontend
    for entry in body:
        assert set(entry) == {"name", "kind", "group", "display_name"}


@respx.mock
async def test_resources_kind_filter(runtime_client: AsyncClient) -> None:
    respx.get(f"{RUNTIME_URL}/api/v1/resources").mock(
        return_value=Response(200, json=_RUNTIME_RESOURCES)
    )
    resp = await runtime_client.get("/api/v1/resources", params={"kind": "vector_db"})
    assert [r["name"] for r in resp.json()] == ["kb-support"]


async def test_resources_without_runtime_503(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/resources")
    assert resp.status_code == 503
