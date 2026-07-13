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


_QDRANT_CREATE = {
    "kind": "qdrant",
    "name": "my-kb",
    "display_name": "My KB",
    "url": "http://qdrant.test:6333",
    "api_key_secret": "super-secret-key-123",
    "embedding": {"resource": "default-llm", "model": "text-emb", "dimension": 768},
}


@respx.mock
async def test_create_resource_passes_credentials_through_write_only(
    runtime_client: AsyncClient,
) -> None:
    """Secrets go TO the runtime; the builder response never echoes them."""
    import json

    route = respx.post(f"{RUNTIME_URL}/api/v1/resources").mock(
        return_value=Response(
            201,
            json={**_QDRANT_CREATE, "api_key_secret": "•••"},  # runtime redacts
        )
    )
    resp = await runtime_client.post("/api/v1/resources", json=_QDRANT_CREATE)
    assert resp.status_code == 201
    sent = json.loads(route.calls.last.request.content)
    assert sent["api_key_secret"] == "super-secret-key-123"  # forwarded to the runtime
    body = resp.json()
    assert body == {
        "name": "my-kb",
        "kind": "qdrant",
        "group": "vector_db",
        "display_name": "My KB",
    }
    assert "secret" not in resp.text  # nothing credential-shaped comes back


@respx.mock
async def test_create_resource_surfaces_runtime_rejection(runtime_client: AsyncClient) -> None:
    respx.post(f"{RUNTIME_URL}/api/v1/resources").mock(
        return_value=Response(
            422,
            json={
                "valid": False,
                "issues": [
                    {
                        "code": "E022",
                        "severity": "error",
                        "path": "embedding/dimension",
                        "message": "collection has 384 dims, embedding declares 768",
                    }
                ],
            },
        )
    )
    resp = await runtime_client.post("/api/v1/resources", json=_QDRANT_CREATE)
    assert resp.status_code == 422
    issues = resp.json()["issues"]
    assert issues[0]["code"] == "E022"
    assert issues[0]["source"] == "runtime"


@respx.mock
async def test_create_resource_name_conflict(runtime_client: AsyncClient) -> None:
    respx.post(f"{RUNTIME_URL}/api/v1/resources").mock(
        return_value=Response(409, text="resource 'my-kb' already exists")
    )
    resp = await runtime_client.post("/api/v1/resources", json=_QDRANT_CREATE)
    assert resp.status_code == 409


async def test_create_resource_invalid_payload_is_422(runtime_client: AsyncClient) -> None:
    resp = await runtime_client.post("/api/v1/resources", json={"kind": "qdrant", "name": "x"})
    assert resp.status_code == 422  # rejected locally: not a valid Resource shape


@respx.mock
async def test_delete_resource_and_referenced_conflict(runtime_client: AsyncClient) -> None:
    respx.delete(f"{RUNTIME_URL}/api/v1/resources/my-kb").mock(return_value=Response(204))
    assert (await runtime_client.delete("/api/v1/resources/my-kb")).status_code == 204
    respx.delete(f"{RUNTIME_URL}/api/v1/resources/in-use").mock(
        return_value=Response(409, text="referenced by definition 'support-rag'")
    )
    assert (await runtime_client.delete("/api/v1/resources/in-use")).status_code == 409
