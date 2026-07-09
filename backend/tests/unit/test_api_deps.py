"""Studio auth dependency (SPEC §9): require_studio's disabled/enabled branches
and scope check, exercised through a StudioAuth-protected route."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from lga.app import AppServices

# /api/v1/components carries StudioAuth via its router dependency.
PROTECTED = "/api/v1/components"


async def test_auth_disabled_allows_anonymous(client: httpx.AsyncClient, svc: AppServices) -> None:
    # test env → auth_enabled is False → require_studio returns immediately.
    assert svc.settings.auth_enabled is False
    response = await client.get(PROTECTED)
    assert response.status_code == 200


async def test_auth_enabled_rejects_missing_key(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    svc.settings.auth_enabled = True
    response = await client.get(PROTECTED)
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid or missing API key"


async def test_auth_enabled_rejects_wrong_scope_key(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    svc.settings.auth_enabled = True
    key, _info = await svc.apikeys.create(["a2a:invoke"], "narrow")
    response = await client.get(PROTECTED, headers={"X-API-Key": key})
    assert response.status_code == 401


async def test_auth_enabled_accepts_studio_key(client: httpx.AsyncClient, svc: AppServices) -> None:
    svc.settings.auth_enabled = True
    key, _info = await svc.apikeys.create(["studio:*"], "admin")
    response = await client.get(PROTECTED, headers={"X-API-Key": key})
    assert response.status_code == 200
