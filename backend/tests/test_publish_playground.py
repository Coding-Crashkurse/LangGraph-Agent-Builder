"""Publish = runtime draft update + deploy; Playground = ephemeral deploy (SPEC §2.4/§2.5)."""

from __future__ import annotations

import respx
from httpx import AsyncClient, Response

from tests.conftest import RUNTIME_URL, definition, definition_info


def _deployment(name: str = "hello-agent", *, ephemeral: bool = False) -> dict[str, object]:
    endpoint = f"http://gateway.test/a2a/{'_draft/' if ephemeral else ''}{name}"
    return {
        "name": name,
        "version": 1,
        "endpoint_url": endpoint,
        "registry_id": None if ephemeral else "8b9c0d1e-2f30-4a4b-9c5d-6e7f80912345",
    }


@respx.mock
async def test_publish_updates_draft_and_deploys(runtime_client: AsyncClient) -> None:
    await runtime_client.post("/api/v1/flows", json=definition())
    put_route = respx.put(f"{RUNTIME_URL}/api/v1/definitions/hello-agent").mock(
        return_value=Response(200, json=definition_info())
    )
    deploy_route = respx.post(f"{RUNTIME_URL}/api/v1/definitions/hello-agent/deploy").mock(
        return_value=Response(200, json=_deployment())
    )
    resp = await runtime_client.post("/api/v1/flows/hello-agent/publish")
    assert resp.status_code == 200
    body = resp.json()
    assert body["endpoint_url"] == "http://gateway.test/a2a/hello-agent"
    assert body["version"] == 1
    assert body["registry_id"]
    assert put_route.called
    assert deploy_route.called
    # the draft sent to the runtime is the canonical definition
    import json

    sent = json.loads(put_route.calls.last.request.content)
    assert sent["name"] == "hello-agent"
    assert [n["id"] for n in sent["nodes"]] == ["call_1", "end_1", "start_1"]


@respx.mock
async def test_publish_creates_missing_draft(runtime_client: AsyncClient) -> None:
    await runtime_client.post("/api/v1/flows", json=definition())
    respx.put(f"{RUNTIME_URL}/api/v1/definitions/hello-agent").mock(
        return_value=Response(404, text="unknown definition")
    )
    create_route = respx.post(f"{RUNTIME_URL}/api/v1/definitions").mock(
        return_value=Response(201, json=definition_info())
    )
    respx.post(f"{RUNTIME_URL}/api/v1/definitions/hello-agent/deploy").mock(
        return_value=Response(200, json=_deployment())
    )
    resp = await runtime_client.post("/api/v1/flows/hello-agent/publish")
    assert resp.status_code == 200
    assert create_route.called


@respx.mock
async def test_publish_surfaces_runtime_rejection(runtime_client: AsyncClient) -> None:
    """Runtime 422 (authoritative) → 422 with issues marked source=runtime."""
    await runtime_client.post("/api/v1/flows", json=definition())
    respx.put(f"{RUNTIME_URL}/api/v1/definitions/hello-agent").mock(
        return_value=Response(200, json=definition_info())
    )
    respx.post(f"{RUNTIME_URL}/api/v1/definitions/hello-agent/deploy").mock(
        return_value=Response(
            422,
            json={
                "valid": False,
                "issues": [
                    {
                        "code": "E020",
                        "severity": "error",
                        "path": "nodes/call_1/config/resource",
                        "message": "unknown resource",
                    }
                ],
            },
        )
    )
    resp = await runtime_client.post("/api/v1/flows/hello-agent/publish")
    assert resp.status_code == 422
    issues = resp.json()["issues"]
    assert issues[0]["code"] == "E020"
    assert issues[0]["source"] == "runtime"


async def test_publish_without_runtime_is_503(client: AsyncClient) -> None:
    await client.post("/api/v1/flows", json=definition())
    resp = await client.post("/api/v1/flows/hello-agent/publish")
    assert resp.status_code == 503


async def test_publish_unparseable_draft_is_422_local(client: AsyncClient) -> None:
    draft = definition()
    draft["nodes"][1]["config"] = {}  # not a valid llm_call config
    await client.post("/api/v1/flows", json=draft)
    resp = await client.post("/api/v1/flows/hello-agent/publish")
    assert resp.status_code == 422
    assert all(i["source"] == "local" for i in resp.json()["issues"])


@respx.mock
async def test_playground_deploys_ephemeral(runtime_client: AsyncClient) -> None:
    await runtime_client.post("/api/v1/flows", json=definition())
    respx.put(f"{RUNTIME_URL}/api/v1/definitions/hello-agent").mock(
        return_value=Response(200, json=definition_info())
    )
    deploy_route = respx.post(f"{RUNTIME_URL}/api/v1/definitions/hello-agent/deploy").mock(
        return_value=Response(200, json=_deployment(ephemeral=True))
    )
    resp = await runtime_client.post("/api/v1/flows/hello-agent/playground")
    assert resp.status_code == 200
    assert resp.json()["endpoint_url"].endswith("/a2a/_draft/hello-agent")
    assert deploy_route.calls.last.request.url.params["ephemeral"] == "true"
