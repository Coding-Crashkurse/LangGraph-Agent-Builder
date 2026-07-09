"""Template gallery API (SPEC §9.9): listing bundled templates and instantiating
a fresh draft flow, plus the unknown-template 404."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from lga.app import AppServices


async def test_list_templates_exposes_metadata(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/templates")
    assert response.status_code == 200
    templates = response.json()
    assert templates, "starter templates should be bundled"
    sample = templates[0]
    assert {"id", "name", "description", "node_count"} <= set(sample)


async def test_create_from_template_makes_a_draft(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    templates = (await client.get("/api/v1/templates")).json()
    template_id = templates[0]["id"]

    before = {row.slug for row in await svc.flows.list()}
    response = await client.post(f"/api/v1/flows/from-template/{template_id}")
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["id"]

    after = {row.slug for row in await svc.flows.list()}
    assert created["slug"] in after
    assert created["slug"] not in before  # a genuinely new flow row


async def test_create_from_unknown_template_is_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/api/v1/flows/from-template/no-such-template")
    assert response.status_code == 404
    assert response.json()["detail"] == "template not found"
