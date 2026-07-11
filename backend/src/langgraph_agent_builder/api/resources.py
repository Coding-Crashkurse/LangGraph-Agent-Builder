"""Resources layer API (Resources): CRUD + health for the four resource types.

A second config plane beside the flow canvas. ``model_provider``,
``knowledge_base`` and ``a2a_agent`` are backed by dedicated rows; ``mcp_server``
delegates to the existing MCP-servers store (no duplicate storage). Values
reference resources by name via ``{"$resource": "<name>"}``.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from langgraph_agent_builder.api.deps import Services, StudioAuth

router = APIRouter(prefix="/resources", tags=["resources"], dependencies=[StudioAuth])

ResourceType = Literal["model_provider", "knowledge_base", "mcp_server", "a2a_agent"]


class ResourceBody(BaseModel):
    name: str
    config: dict[str, Any] = Field(default_factory=dict)


@router.get("/{rtype}")
async def list_resources(rtype: ResourceType, svc: Services) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = await svc.resources.list(rtype)
    return items


@router.post("/{rtype}", status_code=201)
async def upsert_resource(rtype: ResourceType, body: ResourceBody, svc: Services) -> dict[str, Any]:
    created: dict[str, Any] = await svc.resources.upsert(rtype, body.name, body.config)
    return created


@router.delete("/{rtype}/{name}", status_code=204)
async def delete_resource(rtype: ResourceType, name: str, svc: Services) -> None:
    if not await svc.resources.delete(rtype, name):
        raise HTTPException(404, "resource not found")


@router.post("/{rtype}/{name}/test")
async def test_resource(rtype: ResourceType, name: str, svc: Services) -> dict[str, Any]:
    """Health probe: E906 (model auth), E902/E903/E904 (knowledge base),
    E905 (mcp server), E907 (a2a agent card fetch). Never raises for a failing
    probe — returns ``{ok: false, error, code}``; 404 only when absent."""
    if await svc.resources.get(rtype, name) is None:
        raise HTTPException(404, "resource not found")
    report: dict[str, Any] = await svc.resources.health(rtype, name)
    return report
