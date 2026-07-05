"""Component system: base classes, registry and the built-in palette."""

from graphforge.components.base import (
    BaseComponent,
    BuildContext,
    ComponentConfig,
    NodeFn,
    RouterComponent,
    ToolProviderComponent,
)
from graphforge.components.registry import ComponentRegistry, register, registry

__all__ = [
    "BaseComponent",
    "BuildContext",
    "ComponentConfig",
    "ComponentRegistry",
    "NodeFn",
    "RouterComponent",
    "ToolProviderComponent",
    "register",
    "registry",
]
