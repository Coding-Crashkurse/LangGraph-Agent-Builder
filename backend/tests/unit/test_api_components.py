"""Components API (SPEC §9.2): descriptor listing with ETag/304 caching and the
on_field_change config round-trip, including the unknown-component 404."""

from __future__ import annotations

import httpx


async def test_list_components_returns_descriptors_with_etag(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/components")
    assert response.status_code == 200
    assert response.headers.get("ETag")
    ids = {c["component_id"] for c in response.json()}
    assert "lga.io.start" in ids
    # legacy components are filtered out of the listing
    assert all(c.get("legacy") is not True for c in response.json())


async def test_list_components_conditional_get_returns_304(
    client: httpx.AsyncClient,
) -> None:
    first = await client.get("/api/v1/components")
    etag = first.headers["ETag"]
    cached = await client.get("/api/v1/components", headers={"If-None-Match": etag})
    assert cached.status_code == 304


async def test_config_change_roundtrips_value(client: httpx.AsyncClient) -> None:
    # default on_field_change writes value into config and echoes the descriptor.
    response = await client.post(
        "/api/v1/components/lga.io.start/config",
        json={"config": {}, "changed_field": "input_type", "value": "chat"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["config"]["input_type"] == "chat"
    assert isinstance(body["fields"], list)
    assert "input_ports" in body
    assert "outputs" in body


async def test_config_change_unknown_component_is_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/components/lga.not.real/config",
        json={"config": {}, "changed_field": "x", "value": 1},
    )
    assert response.status_code == 404
    assert "lga.not.real" in response.json()["detail"]
