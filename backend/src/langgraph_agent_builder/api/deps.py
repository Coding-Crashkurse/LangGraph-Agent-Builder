"""FastAPI dependencies: service container access and authentication."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Depends, Header, Request

from langgraph_agent_builder.auth import Principal

if TYPE_CHECKING:
    from langgraph_agent_builder.app import BuilderServices


def get_services(request: Request) -> BuilderServices:
    return cast("BuilderServices", request.app.state.svc)


Services = Annotated["BuilderServices", Depends(get_services)]


async def current_principal(
    svc: Services,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    return await svc.authenticator.authenticate(authorization)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
