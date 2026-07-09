"""Settings/misc API (SPEC §9.6–§9.8, §11.7): variables, api keys, files (incl.
tokened download and the too-large 413), mcp servers, mcp client config, and the
health/version/config endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import httpx

if TYPE_CHECKING:
    from lga.app import AppServices


# ------------------------------------------------------------------ variables
async def test_variable_crud_and_credential_is_write_only(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        "/api/v1/variables", json={"name": "region", "value": "eu", "kind": "generic"}
    )
    assert created.status_code == 201
    assert created.json() == {"name": "region", "kind": "generic"}

    await client.post(
        "/api/v1/variables",
        json={"name": "openai_key", "value": "sk-secret", "kind": "credential"},
    )
    listed = await client.get("/api/v1/variables")
    assert listed.status_code == 200
    by_name = {v["name"]: v for v in listed.json()}
    assert by_name["region"]["kind"] == "generic"
    # credential value is never echoed back
    assert "value" not in by_name["openai_key"]

    deleted = await client.delete("/api/v1/variables/region")
    assert deleted.status_code == 204
    missing = await client.delete("/api/v1/variables/region")
    assert missing.status_code == 404


async def test_variable_invalid_kind_is_422(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/variables", json={"name": "x", "value": "y", "kind": "bogus"}
    )
    assert response.status_code == 422  # pydantic pattern rejects


# ------------------------------------------------------------------ api keys
async def test_apikey_create_list_revoke(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/v1/apikeys", json={"name": "ci", "scopes": ["studio:*"]})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["key"].startswith("lga_sk_")  # plaintext returned exactly once
    key_id = body["id"]

    listed = await client.get("/api/v1/apikeys")
    assert key_id in {k["id"] for k in listed.json()}
    # the stored listing never contains the plaintext key
    assert all("key" not in k for k in listed.json())

    revoked = await client.delete(f"/api/v1/apikeys/{key_id}")
    assert revoked.status_code == 204
    missing = await client.delete("/api/v1/apikeys/does-not-exist")
    assert missing.status_code == 404


async def test_apikey_unknown_scope_is_422(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/apikeys", json={"scopes": ["not-a-scope"]})
    assert response.status_code == 422
    assert "not-a-scope" in response.json()["detail"]


# ------------------------------------------------------------------ files
async def test_file_upload_list_and_tokened_download(
    client: httpx.AsyncClient,
) -> None:
    upload = await client.post(
        "/api/v1/files",
        files={"file": ("note.txt", b"hello files", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    info = upload.json()
    assert info["size"] == 11
    file_id = info["file_id"]

    listed = await client.get("/api/v1/files")
    assert file_id in {f["file_id"] for f in listed.json()}

    token = parse_qs(urlparse(info["url"]).query)["token"][0]
    good = await client.get(f"/api/v1/files/{file_id}?token={token}")
    assert good.status_code == 200
    assert good.content == b"hello files"
    assert good.headers["content-type"].startswith("text/plain")

    # wrong token → 404 (tokened access, SPEC §9.6)
    bad = await client.get(f"/api/v1/files/{file_id}?token=wrong")
    assert bad.status_code == 404


async def test_download_unknown_file_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/files/nope?token=x")
    assert response.status_code == 404
    assert response.json()["detail"] == "file not found"


async def test_file_too_large_is_413(client: httpx.AsyncClient, svc: AppServices) -> None:
    svc.settings.max_file_size_mb = 0  # any non-empty upload now exceeds the limit
    response = await client.post(
        "/api/v1/files",
        files={"file": ("big.bin", b"x", "application/octet-stream")},
    )
    assert response.status_code == 413
    assert "upload limit" in response.json()["detail"]


# ------------------------------------------------------------------ mcp servers
async def test_mcp_server_crud(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/v1/mcp-servers",
        json={"name": "weather", "transport": "streamable_http", "config": {"url": "u"}},
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "weather"

    listed = await client.get("/api/v1/mcp-servers")
    assert "weather" in {s["name"] for s in listed.json()}

    deleted = await client.delete("/api/v1/mcp-servers/weather")
    assert deleted.status_code == 204
    missing = await client.delete("/api/v1/mcp-servers/weather")
    assert missing.status_code == 404


async def test_mcp_server_invalid_transport_is_422(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/mcp-servers", json={"name": "x", "transport": "carrier-pigeon"}
    )
    assert response.status_code == 422


async def test_mcp_client_config_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/mcp/config")
    assert response.status_code == 200
    lga = response.json()["mcpServers"]["lga"]
    assert lga["type"] == "http"
    assert lga["url"].endswith("/mcp")
    # auth disabled in test env → no headers block
    assert "headers" not in lga


# ------------------------------------------------------------------ misc
async def test_health_reports_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert body["checkpointer"] is True
    assert "local" in body["vector_backends"]


async def test_health_unprefixed_route(client: httpx.AsyncClient) -> None:
    # misc_router is also mounted without the /api/v1 prefix for load balancers.
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_version_reports_packages(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/version")
    assert response.status_code == 200
    body = response.json()
    assert body["lga"]
    assert "langgraph" in body
    assert body["db_backend"] in {"sqlite", "postgres"}


async def test_config_masks_secret_key(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    # the Fernet key is resolved at boot; the endpoint must never leak it.
    assert data["secret_key"] in {"***", ""}
    assert not data["secret_key"].startswith("lga")
    assert data["env"] == "test"
