"""``/resources`` — thin proxy to the runtime's resource API (SPEC §3).

Listing returns names + kinds only. Create/delete pass straight through to
the runtime: credentials in a create payload are write-only — the runtime
stores them encrypted; the builder never persists or echoes them.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Query

from langgraph_agent_builder.api.deps import CurrentPrincipal, Services
from langgraph_agent_builder.services.runtime import ResourceGroup, ResourceSummary

router = APIRouter(tags=["resources"])


@router.get("/resources")
async def list_resources(
    svc: Services,
    principal: CurrentPrincipal,
    kind: Annotated[ResourceGroup | None, Query()] = None,
) -> list[ResourceSummary]:
    return await svc.gateway.list_resources(kind, principal.token)


@router.post("/resources", status_code=201)
async def create_resource(
    payload: Annotated[dict[str, Any], Body()],
    svc: Services,
    principal: CurrentPrincipal,
) -> ResourceSummary:
    """Create a resource on the runtime (write-only credential pass-through)."""
    return await svc.gateway.create_resource(payload, principal.token)


@router.delete("/resources/{name}", status_code=204)
async def delete_resource(name: str, svc: Services, principal: CurrentPrincipal) -> None:
    await svc.gateway.delete_resource(name, principal.token)
