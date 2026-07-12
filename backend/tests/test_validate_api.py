"""POST /flows/validate — merged local + runtime issues (SPEC §2.3, §3)."""

from __future__ import annotations

import respx
from httpx import AsyncClient, Response

from tests.conftest import RUNTIME_URL, definition


async def test_local_only_when_no_runtime(client: AsyncClient) -> None:
    broken = definition(edges=[])  # end unreachable / no inbound
    resp = await client.post("/api/v1/flows/validate", json=broken)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["runtime_checked"] is False
    codes = {i["code"] for i in body["issues"]}
    assert "E030" in codes
    assert all(i["source"] == "local" for i in body["issues"])


async def test_valid_flow_passes_locally(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/flows/validate", json=definition())
    body = resp.json()
    assert body["valid"] is True
    assert body["issues"] == []


@respx.mock
async def test_runtime_issues_merged(runtime_client: AsyncClient) -> None:
    respx.post(f"{RUNTIME_URL}/api/v1/definitions/validate").mock(
        return_value=Response(
            200,
            json={
                "valid": False,
                "issues": [
                    {
                        "code": "E020",
                        "severity": "error",
                        "path": "nodes/call_1/config/resource",
                        "message": "unknown resource 'default-llm'",
                    }
                ],
            },
        )
    )
    resp = await runtime_client.post("/api/v1/flows/validate", json=definition())
    body = resp.json()
    assert body["runtime_checked"] is True
    assert body["valid"] is False
    runtime_issues = [i for i in body["issues"] if i["source"] == "runtime"]
    assert [i["code"] for i in runtime_issues] == ["E020"]


@respx.mock
async def test_runtime_duplicates_deduped(runtime_client: AsyncClient) -> None:
    """The runtime re-runs structural checks; identical (code, path) stay local."""
    broken = definition(edges=[])
    local_codes = [("E030", "nodes/end_1")]
    respx.post(f"{RUNTIME_URL}/api/v1/definitions/validate").mock(
        return_value=Response(
            200,
            json={
                "valid": False,
                "issues": [
                    {
                        "code": code,
                        "severity": "error",
                        "path": path,
                        "message": "duplicate of local",
                    }
                    for code, path in local_codes
                ],
            },
        )
    )
    resp = await runtime_client.post("/api/v1/flows/validate", json=broken)
    body = resp.json()
    matching = [i for i in body["issues"] if (i["code"], i["path"]) in set(local_codes)]
    assert matching
    assert all(i["source"] == "local" for i in matching)


@respx.mock
async def test_runtime_check_skippable_for_silent_local_validate(
    runtime_client: AsyncClient,
) -> None:
    """The canvas's debounced re-validate runs local-only (?runtime=false)."""
    route = respx.post(f"{RUNTIME_URL}/api/v1/definitions/validate").mock(
        return_value=Response(200, json={"valid": True, "issues": []})
    )
    resp = await runtime_client.post(
        "/api/v1/flows/validate", params={"runtime": "false"}, json=definition()
    )
    body = resp.json()
    assert body["runtime_checked"] is False
    assert not route.called


@respx.mock
async def test_unreachable_runtime_degrades(runtime_client: AsyncClient) -> None:
    import httpx

    respx.post(f"{RUNTIME_URL}/api/v1/definitions/validate").mock(
        side_effect=httpx.ConnectError("refused")
    )
    resp = await runtime_client.post("/api/v1/flows/validate", json=definition())
    body = resp.json()
    assert body["runtime_checked"] is False
    assert body["valid"] is True


@respx.mock
async def test_token_forwarded_to_runtime(runtime_client: AsyncClient) -> None:
    route = respx.post(f"{RUNTIME_URL}/api/v1/definitions/validate").mock(
        return_value=Response(200, json={"valid": True, "issues": []})
    )
    await runtime_client.post("/api/v1/flows/validate", json=definition())
    assert route.calls.last.request.headers["Authorization"] == "Bearer dev-token"
