"""``GET /node-types`` — the platform node catalog with UI metadata (SPEC §3)."""

from __future__ import annotations

from fastapi import APIRouter

from langgraph_agent_builder.api.deps import CurrentPrincipal
from langgraph_agent_builder.node_types import CATALOG, NodeCatalog

router = APIRouter(tags=["catalog"])


@router.get("/node-types")
async def node_types(_principal: CurrentPrincipal) -> NodeCatalog:
    return CATALOG
