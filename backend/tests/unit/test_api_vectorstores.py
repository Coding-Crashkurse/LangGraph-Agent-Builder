"""Vector store connections API (SPEC §9.9): backend listing, connection CRUD,
and collection management against the always-available ``local`` backend."""

from __future__ import annotations

import httpx


async def test_list_backends(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/vectorstores/backends")
    assert response.status_code == 200
    body = response.json()
    assert "local" in body["installed"]
    # every declared backend name is advertised under "all"
    assert set(body["all"]) >= {"local", "pgvector", "qdrant", "weaviate", "chroma"}


async def test_default_local_connection_present_and_healthy(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/vectorstores")
    assert response.status_code == 200
    conns = {c["name"]: c for c in response.json()}
    assert "local" in conns  # provisioned at boot
    assert conns["local"]["ok"] is True
    assert conns["local"]["backend"] == "local"


async def test_create_connection_unknown_backend_is_422(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/api/v1/vectorstores", json={"name": "bad", "backend": "wat"})
    assert response.status_code == 422
    assert "wat" in response.json()["detail"]


async def test_create_and_delete_connection(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/v1/vectorstores", json={"name": "scratch", "backend": "local"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "scratch"

    deleted = await client.delete("/api/v1/vectorstores/scratch")
    assert deleted.status_code == 204

    # second delete of the same name → 404
    again = await client.delete("/api/v1/vectorstores/scratch")
    assert again.status_code == 404
    assert again.json()["detail"] == "connection not found"


async def test_list_collections_unknown_connection_is_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/vectorstores/ghost/collections")
    assert response.status_code == 404
    assert response.json()["detail"] == "connection not found"


async def test_create_collection_unknown_connection_is_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/api/v1/vectorstores/ghost/collections", json={"name": "c1"})
    assert response.status_code == 404


async def test_create_then_list_collection_roundtrip(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        "/api/v1/vectorstores/local/collections",
        json={"name": "docs", "dim": 8, "metric": "cosine"},
    )
    assert created.status_code == 201, created.text
    assert created.json() == {"name": "docs", "dim": 8, "metric": "cosine"}

    listed = await client.get("/api/v1/vectorstores/local/collections")
    assert listed.status_code == 200
    names = {c["name"] for c in listed.json()}
    assert "docs" in names
