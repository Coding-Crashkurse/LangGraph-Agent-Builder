"""Components API (SPEC §9.2): descriptors + on_field_change round-trip."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from lga.api.deps import Services, StudioAuth

router = APIRouter(prefix="/components", tags=["components"], dependencies=[StudioAuth])


class ConfigChangeBody(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)
    changed_field: str
    value: Any = None


@router.get("")
async def list_components(svc: Services, request: Request, response: Response) -> Any:
    etag = svc.registry.etag()
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)
    response.headers["ETag"] = etag
    return [cls.descriptor() for cls in svc.registry.all() if not cls.legacy]


@router.post("/{component_id:path}/config")
async def component_config_change(
    component_id: str, body: ConfigChangeBody, svc: Services
) -> dict[str, Any]:
    cls = svc.registry.get(component_id)
    if cls is None:
        raise HTTPException(404, f"unknown component {component_id!r}")
    import asyncio

    instance = cls()
    try:
        config = await asyncio.wait_for(
            asyncio.to_thread(instance.on_field_change, body.config, body.changed_field, body.value)
            if not asyncio.iscoroutinefunction(instance.on_field_change)
            else instance.on_field_change(body.config, body.changed_field, body.value),
            timeout=10.0,
        )
    except TimeoutError as exc:
        raise HTTPException(504, "on_field_change timed out (10s)") from exc
    descriptor = cls.descriptor(config)
    return {
        "config": config,
        "fields": descriptor["fields"],
        "outputs": descriptor["outputs"],
        "input_ports": descriptor["input_ports"],
    }
