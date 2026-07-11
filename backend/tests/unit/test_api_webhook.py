"""Webhook trigger API (SPEC §9.5): auth gate, flow resolution, payload capture,
header vars, and the FlowNotRunnable → 422 path. Exercised end-to-end through the
ASGI client so real HTTP status codes and bodies are asserted."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import httpx

from tests.conftest import hello_spec

if TYPE_CHECKING:
    from langgraph_agent_builder.app import AppServices


async def _create_draft(client: httpx.AsyncClient, spec: dict[str, Any]) -> str:
    response = await client.post("/api/v1/flows", json={"spec": spec})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_webhook_requires_auth_by_default(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    # webhook_auth defaults to True; a call without X-API-Key is rejected 401.
    assert svc.settings.webhook_auth is True
    await _create_draft(client, hello_spec("wh-auth"))
    response = await client.post("/api/v1/webhook/wh-auth", json={"any": "thing"})
    assert response.status_code == 401
    assert "webhook:invoke" in response.json()["detail"]


async def test_webhook_valid_key_starts_run(client: httpx.AsyncClient, svc: AppServices) -> None:
    await _create_draft(client, hello_spec("wh-keyed"))
    key, _info = await svc.apikeys.create(["webhook:invoke"], "hook")
    response = await client.post(
        "/api/v1/webhook/wh-keyed",
        json={"ticket": 7},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 202, response.text
    assert response.json()["run_id"]


async def test_webhook_wrong_scope_key_rejected(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    await _create_draft(client, hello_spec("wh-scope"))
    # a studio key does NOT carry webhook:invoke → still 401
    key, _info = await svc.apikeys.create(["a2a:invoke"], "wrong")
    response = await client.post("/api/v1/webhook/wh-scope", json={}, headers={"X-API-Key": key})
    assert response.status_code == 401


async def test_webhook_unknown_flow_is_404(client: httpx.AsyncClient, svc: AppServices) -> None:
    svc.settings.webhook_auth = False
    response = await client.post("/api/v1/webhook/does-not-exist", json={})
    assert response.status_code == 404
    assert response.json()["detail"] == "flow not found"


async def test_webhook_non_json_body_captured_as_raw(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    svc.settings.webhook_auth = False
    await _create_draft(client, hello_spec("wh-raw"))
    response = await client.post(
        "/api/v1/webhook/wh-raw",
        content=b"not json at all",
        headers={"Content-Type": "text/plain"},
    )
    # invalid JSON is wrapped, not rejected — the run still starts (202)
    assert response.status_code == 202, response.text
    assert response.json()["run_id"]


async def test_webhook_header_vars_do_not_break_run(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    svc.settings.webhook_auth = False
    await _create_draft(client, hello_spec("wh-vars"))
    response = await client.post(
        "/api/v1/webhook/wh-vars",
        json={"hello": "world"},
        headers={"X-LAB-Var-Tenant": "acme"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["run_id"]


async def test_webhook_non_runnable_flow_is_422(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    svc.settings.webhook_auth = False
    spec = copy.deepcopy(hello_spec("wh-broken"))
    # unknown component: parses fine (schema-only) but fails to compile → 422
    spec["nodes"][1]["component_id"] = "lab.nope.missing"
    await _create_draft(client, spec)
    response = await client.post("/api/v1/webhook/wh-broken", json={})
    assert response.status_code == 422, response.text
