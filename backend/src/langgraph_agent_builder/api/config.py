"""Frontend bootstrap config and health probes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

import langgraph_agent_builder
from langgraph_agent_builder.api.deps import CurrentPrincipal, Services
from langgraph_agent_builder.services.runtime import RuntimeHealth

router = APIRouter(tags=["config"])


class FrontendConfig(BaseModel):
    version: str
    auth_mode: str
    oidc_issuer: str
    oidc_client_id: str
    runtime_configured: bool
    resources_ui_url: str
    registry_ui_url: str


@router.get("/config")
async def get_config(svc: Services) -> FrontendConfig:
    s = svc.settings
    return FrontendConfig(
        version=langgraph_agent_builder.__version__,
        auth_mode=s.auth_mode,
        oidc_issuer=s.oidc_issuer,
        oidc_client_id=s.oidc_client_id,
        runtime_configured=bool(s.runtime_url),
        resources_ui_url=s.resources_ui_url,
        registry_ui_url=s.registry_ui_url,
    )


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/runtime/health")
async def runtime_health(svc: Services, principal: CurrentPrincipal) -> RuntimeHealth:
    """Liveness of the configured agentplane runtime (drives the status dot)."""
    return await svc.gateway.health(principal.token)
