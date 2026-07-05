"""Component discovery + registry + /api/components payload (CLAUDE.md §6.2)."""

import importlib
import logging
import pkgutil
from types import ModuleType
from typing import Any

from graphforge.components.base import BaseComponent, RouterComponent, ToolProviderComponent

logger = logging.getLogger(__name__)

_REQUIRED_ATTRS = ("name", "display_name", "description", "category", "config_model")


class DuplicateComponentError(RuntimeError):
    pass


class ComponentRegistry:
    def __init__(self) -> None:
        self._components: dict[str, type[BaseComponent]] = {}
        self._modules: list[ModuleType] = []

    # -- registration -------------------------------------------------------

    def add[C: type[BaseComponent]](self, cls: C) -> C:
        for attr in _REQUIRED_ATTRS:
            if not getattr(cls, attr, None):
                raise TypeError(f"component {cls.__qualname__} is missing '{attr}'")
        existing = self._components.get(cls.name)
        if existing is not None and existing is not cls:
            # same module re-imported (dev reload) is fine; two classes are not
            if f"{existing.__module__}.{existing.__qualname__}" != (
                f"{cls.__module__}.{cls.__qualname__}"
            ):
                raise DuplicateComponentError(
                    f"duplicate component name '{cls.name}': "
                    f"{existing.__module__} and {cls.__module__}"
                )
        self._components[cls.name] = cls
        return cls

    # -- discovery ----------------------------------------------------------

    def load(self, *, include_testing: bool = False) -> None:
        """Import every module in components/builtin and components/user."""
        self._components.clear()
        self._modules.clear()
        for package_name in ("graphforge.components.builtin", "graphforge.components.user"):
            package = importlib.import_module(package_name)
            for info in pkgutil.iter_modules(package.__path__):
                if info.name == "testing" and not include_testing:
                    continue
                module_name = f"{package_name}.{info.name}"
                module = importlib.import_module(module_name)
                module = importlib.reload(module)  # re-run @register after clear()
                self._modules.append(module)
        logger.info("component registry loaded: %s", sorted(self._components))

    # -- access --------------------------------------------------------------

    def get(self, name: str) -> type[BaseComponent] | None:
        return self._components.get(name)

    def all(self) -> dict[str, type[BaseComponent]]:
        return dict(self._components)

    @staticmethod
    def kind_of(cls: type[BaseComponent]) -> str:
        if issubclass(cls, RouterComponent):
            return "router"
        if issubclass(cls, ToolProviderComponent):
            return "tool_provider"
        return "node"

    def payload(self) -> list[dict[str, Any]]:
        """The /api/components response; the frontend builds palette + forms
        exclusively from this (adding a component must never require FE changes)."""
        items: list[dict[str, Any]] = []
        for cls in sorted(self._components.values(), key=lambda c: (c.category, c.name)):
            kind = self.kind_of(cls)
            item: dict[str, Any] = {
                "name": cls.name,
                "display_name": cls.display_name,
                "description": cls.description,
                "category": cls.category,
                "version": cls.version,
                "kind": kind,
                "accepts_attachments": list(cls.accepts_attachments),
                "state_reads": list(cls.state_reads),
                "state_writes": list(cls.state_writes),
                "config_json_schema": cls.config_model.model_json_schema(),
            }
            if kind == "router":
                item["outputs_static"] = cls.outputs_static  # type: ignore[attr-defined]
                item["outputs_from_config"] = cls.outputs_from_config  # type: ignore[attr-defined]
            if kind == "tool_provider":
                item["attachment_kind"] = cls.attachment_kind  # type: ignore[attr-defined]
            items.append(item)
        return items


registry = ComponentRegistry()


def register[C: type[BaseComponent]](cls: C) -> C:
    """Class decorator: register a component in the global registry."""
    return registry.add(cls)
