"""Request-scoped access to app-level singletons (set up in the lifespan)."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from graphforge.components.registry import ComponentRegistry
from graphforge.runtime.events import EventBus
from graphforge.runtime.manager import FlowRuntimeManager
from graphforge.settings import Settings


def get_state(request: Request):
    return request.app.state


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> ComponentRegistry:
    return request.app.state.registry


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


def get_manager(request: Request) -> FlowRuntimeManager:
    return request.app.state.manager


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessionmaker


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RegistryDep = Annotated[ComponentRegistry, Depends(get_registry)]
BusDep = Annotated[EventBus, Depends(get_bus)]
ManagerDep = Annotated[FlowRuntimeManager, Depends(get_manager)]
SessionmakerDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]
