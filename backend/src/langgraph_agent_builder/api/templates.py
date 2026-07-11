"""Template gallery API (SPEC §9.9)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from lga.api.deps import Services, StudioAuth
from lga.api.flows import flow_info
from lga.services import templates

router = APIRouter(tags=["templates"], dependencies=[StudioAuth])


@router.get("/templates")
async def list_templates() -> list[dict[str, Any]]:
    return templates.list_templates()


@router.post("/flows/from-template/{template_id}", status_code=201)
async def create_from_template(template_id: str, svc: Services) -> dict[str, Any]:
    existing = {row.slug for row in await svc.flows.list()}
    spec = templates.instantiate(template_id, existing)
    if spec is None:
        raise HTTPException(404, "template not found")
    row = await svc.flows.create(spec)
    return flow_info(row)
