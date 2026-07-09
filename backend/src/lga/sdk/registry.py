"""Component discovery & registry (SPEC §4.8) — no eval, ever.

Sources:
1. Entry points: ``[project.entry-points."lga.components"]`` → package walked.
2. Component dirs (``LGA_COMPONENTS_PATH``): ``<dir>/<category>/<module>.py``
   imported via importlib; syntax errors become registry diagnostics.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import inspect
import logging
import pkgutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from lga.errors import LgaRuntimeError
from lga.sdk.component import Component

logger = logging.getLogger("lga.registry")

ENTRY_POINT_GROUP = "lga.components"


class DuplicateComponentError(LgaRuntimeError):
    pass


@dataclass
class RegistryDiagnostic:
    origin: str
    message: str


@dataclass
class ComponentRegistry:
    components: dict[str, type[Component]] = field(default_factory=dict)
    origins: dict[str, str] = field(default_factory=dict)
    diagnostics: list[RegistryDiagnostic] = field(default_factory=list)
    include_testing: bool = True

    # ---------------------------------------------------------------- registration
    def register(self, cls: type[Component], origin: str = "manual") -> None:
        cid = getattr(cls, "component_id", None)
        if not cid:
            raise ValueError(f"{cls.__name__} has no component_id")
        existing = self.components.get(cid)
        if existing is not None and existing is not cls:
            raise DuplicateComponentError(
                f"duplicate component_id {cid!r}: {self.origins.get(cid)} and {origin}"
            )
        self.components[cid] = cls
        self.origins[cid] = origin

    def get(self, component_id: str) -> type[Component] | None:
        return self.components.get(component_id)

    def all(self, include_legacy: bool = True) -> list[type[Component]]:
        items = sorted(self.components.values(), key=lambda c: c.component_id)
        if include_legacy:
            return items
        return [c for c in items if not c.legacy]

    # ---------------------------------------------------------------- discovery
    def discover(self, extra_dirs: list[Path] | None = None) -> None:
        for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
            try:
                module = ep.load()
            except Exception as exc:  # import errors must not crash the server
                self.diagnostics.append(
                    RegistryDiagnostic(origin=f"entry-point:{ep.name}", message=str(exc))
                )
                logger.warning("failed to load component entry point %s: %s", ep.name, exc)
                continue
            self._register_module_tree(module, origin=f"entry-point:{ep.name}")
        for directory in extra_dirs or []:
            self._scan_dir(directory)

    def _register_module_tree(self, module: ModuleType, origin: str) -> None:
        self._register_module(module, origin)
        if hasattr(module, "__path__"):
            for info in pkgutil.walk_packages(module.__path__, prefix=module.__name__ + "."):
                try:
                    sub = importlib.import_module(info.name)
                except Exception as exc:
                    self.diagnostics.append(
                        RegistryDiagnostic(origin=f"{origin}:{info.name}", message=str(exc))
                    )
                    continue
                self._register_module(sub, origin=f"{origin}:{info.name}")

    def _register_module(self, module: ModuleType, origin: str) -> None:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Component)
                and obj is not Component
                and not inspect.isabstract(obj)
                and getattr(obj, "component_id", None)
                and obj.__module__ == module.__name__
            ):
                if not self.include_testing and obj.category == "testing":
                    continue
                self.register(obj, origin=origin)

    def _scan_dir(self, directory: Path) -> None:
        directory = directory.expanduser()
        if not directory.is_dir():
            self.diagnostics.append(
                RegistryDiagnostic(origin=str(directory), message="components dir not found")
            )
            return
        for py in sorted(directory.rglob("*.py")):
            if py.name.startswith("_"):
                continue
            rel = py.relative_to(directory).with_suffix("")
            mod_name = "lga_user_components." + ".".join(rel.parts)
            try:
                spec = importlib.util.spec_from_file_location(mod_name, py)
                assert spec
                assert spec.loader
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
            except Exception as exc:
                self.diagnostics.append(RegistryDiagnostic(origin=str(py), message=str(exc)))
                logger.warning("failed to import component file %s: %s", py, exc)
                continue
            self._register_module(module, origin=str(py))

    # ---------------------------------------------------------------- fingerprint
    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for cid, cls in sorted(self.components.items()):
            h.update(f"{cid}@{cls.version};".encode())
        return h.hexdigest()[:16]

    def etag(self) -> str:
        return f'W/"{self.fingerprint()}"'


_default_registry: ComponentRegistry | None = None


def get_registry() -> ComponentRegistry:
    """Process-wide default registry with built-ins discovered; lazy."""
    global _default_registry
    if _default_registry is None:
        reg = ComponentRegistry()
        reg.discover()
        if not reg.components:
            # entry points unavailable (e.g. non-installed checkout): walk built-ins directly
            import lga.components as builtin

            reg._register_module_tree(builtin, origin="builtin")
        _default_registry = reg
    return _default_registry


def reset_registry() -> None:
    global _default_registry
    _default_registry = None
