"""GET /api/components — the palette payload (CLAUDE.md §6.2)."""

from typing import Any

from fastapi import APIRouter

from graphforge.api.deps import RegistryDep

router = APIRouter(prefix="/api", tags=["components"])


@router.get("/components")
async def list_components(registry: RegistryDep) -> list[dict[str, Any]]:
    return registry.payload()
