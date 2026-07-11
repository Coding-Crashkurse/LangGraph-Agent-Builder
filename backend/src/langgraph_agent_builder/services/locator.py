"""Process-wide service locator.

Set by `build_services`; lets built-in components that genuinely need server
services (flow_as_tool, file_loader) reach them without threading the container
through the SDK. Headless compiles see None and raise a clear error.
"""

from __future__ import annotations

from typing import Any

_current: Any = None


def set_services(services: Any) -> None:
    global _current
    _current = services


def get_services() -> Any:
    return _current


def require_services(feature: str) -> Any:
    if _current is None:
        raise RuntimeError(f"{feature} requires a running lab server (no service context)")
    return _current
