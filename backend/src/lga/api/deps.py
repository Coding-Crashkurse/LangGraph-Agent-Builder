"""FastAPI dependencies: service container access + Studio auth (SPEC §9)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request

if TYPE_CHECKING:
    from lga.app import AppServices


def get_services(request: Request) -> AppServices:
    svc: AppServices = request.app.state.svc
    return svc


Services = Annotated["AppServices", Depends(get_services)]


async def require_studio(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    svc: AppServices = request.app.state.svc
    if not svc.settings.auth_enabled:
        return
    if x_api_key and await svc.apikeys.verify(x_api_key, "studio:*"):
        return
    raise HTTPException(status_code=401, detail="invalid or missing API key")


StudioAuth = Depends(require_studio)
