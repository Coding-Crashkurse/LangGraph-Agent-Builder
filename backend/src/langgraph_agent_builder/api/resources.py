"""``GET /resources`` — proxy to runtime resources, names + kinds only (SPEC §3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

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
