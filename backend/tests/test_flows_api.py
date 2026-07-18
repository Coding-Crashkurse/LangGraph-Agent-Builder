"""CRUD /flows — builder-local drafts incl. layout (SPEC §3)."""

from __future__ import annotations

import httpx
import respx
from httpx import AsyncClient

from tests.conftest import RUNTIME_URL, definition


async def test_create_get_list_delete(client: AsyncClient) -> None:
    created = await client.post("/api/v1/flows", json=definition())
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "hello-agent"
    assert body["definition"]["layout"] == {"nodes": {"start_1": {"x": 0.0, "y": 0.0}}}

    listed = await client.get("/api/v1/flows")
    assert [f["name"] for f in listed.json()] == ["hello-agent"]
    assert listed.json()[0]["expose_kind"] == "a2a"

    fetched = await client.get("/api/v1/flows/hello-agent")
    assert fetched.status_code == 200
    assert fetched.json()["definition"]["nodes"][0]["id"] == "call_1"  # canonical order

    deleted = await client.delete("/api/v1/flows/hello-agent")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/flows/hello-agent")).status_code == 404


async def test_create_duplicate_conflicts(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/flows", json=definition())).status_code == 201
    dup = await client.post("/api/v1/flows", json=definition())
    assert dup.status_code == 409


async def test_create_requires_slug_name(client: AsyncClient) -> None:
    bad = await client.post("/api/v1/flows", json=definition(name="Not A Slug"))
    assert bad.status_code == 422
    issues = bad.json()["issues"]
    assert issues
    assert issues[0]["code"] == "E011"
    assert issues[0]["source"] == "local"

    missing = await client.post("/api/v1/flows", json={"schema_version": 1})
    assert missing.status_code == 422
    assert missing.json()["issues"][0]["code"] == "E010"


async def test_save_updates_draft(client: AsyncClient) -> None:
    await client.post("/api/v1/flows", json=definition())
    changed = definition(description="updated")
    saved = await client.put("/api/v1/flows/hello-agent", json=changed)
    assert saved.status_code == 200
    assert saved.json()["definition"]["description"] == "updated"


async def test_save_name_mismatch_conflicts(client: AsyncClient) -> None:
    await client.post("/api/v1/flows", json=definition())
    renamed = definition(name="other-name")
    resp = await client.put("/api/v1/flows/hello-agent", json=renamed)
    assert resp.status_code == 409


async def test_save_unknown_flow_404(client: AsyncClient) -> None:
    resp = await client.put("/api/v1/flows/missing", json=definition(name="missing"))
    assert resp.status_code == 404


async def test_incomplete_draft_is_saveable(client: AsyncClient) -> None:
    """A half-configured canvas (empty llm_call config) must always save."""
    draft = definition()
    draft["nodes"][1]["config"] = {}  # llm_call without resource/prompt: not parseable
    created = await client.post("/api/v1/flows", json=draft)
    assert created.status_code == 201
    stored = created.json()["definition"]
    node = next(n for n in stored["nodes"] if n["id"] == "call_1")
    assert node["config"] == {}  # stored verbatim, no silent fix-up


@respx.mock
async def test_delete_with_undeploy_removes_the_flow_from_the_platform(
    runtime_client: AsyncClient,
) -> None:
    await runtime_client.post("/api/v1/flows", json=definition())
    undeploy_route = respx.post(f"{RUNTIME_URL}/api/v1/definitions/hello-agent/undeploy").mock(
        return_value=httpx.Response(204)
    )
    delete_route = respx.delete(f"{RUNTIME_URL}/api/v1/definitions/hello-agent").mock(
        return_value=httpx.Response(204)
    )

    deleted = await runtime_client.delete("/api/v1/flows/hello-agent", params={"undeploy": "true"})
    assert deleted.status_code == 204
    assert undeploy_route.called
    assert delete_route.called
    assert (await runtime_client.get("/api/v1/flows/hello-agent")).status_code == 404


@respx.mock
async def test_delete_with_undeploy_tolerates_a_never_published_flow(
    runtime_client: AsyncClient,
) -> None:
    await runtime_client.post("/api/v1/flows", json=definition())
    # Runtime never saw this flow: undeploy 404s, delete 404s - still success.
    respx.post(f"{RUNTIME_URL}/api/v1/definitions/hello-agent/undeploy").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    respx.delete(f"{RUNTIME_URL}/api/v1/definitions/hello-agent").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )

    deleted = await runtime_client.delete("/api/v1/flows/hello-agent", params={"undeploy": "true"})
    assert deleted.status_code == 204
