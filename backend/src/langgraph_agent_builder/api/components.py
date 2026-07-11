"""Components API (SPEC §9.2): descriptors + on_field_change round-trip."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from langgraph_agent_builder.api.deps import Services, StudioAuth
from langgraph_agent_builder.sdk.dynamic import ComponentInitError, invoke_field_change

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
    """HTTP mapping only — the dispatch itself lives in ``langgraph_agent_builder.sdk.dynamic``."""
    cls = svc.registry.get(component_id)
    if cls is None:
        raise HTTPException(404, f"unknown component {component_id!r}")
    try:
        config = await invoke_field_change(cls, body.changed_field, body.value, body.config)
    except TimeoutError as exc:
        raise HTTPException(504, "on_field_change timed out (10s)") from exc
    except ComponentInitError as exc:
        raise HTTPException(422, str(exc)) from exc
    descriptor = cls.descriptor(config)
    return {
        "config": config,
        "fields": descriptor["fields"],
        "outputs": descriptor["outputs"],
        "input_ports": descriptor["input_ports"],
    }
