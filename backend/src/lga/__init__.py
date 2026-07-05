"""lga — LangGraph-native visual agent builder.

Public, semver-stable surface (SPEC §2.7). Everything not exported here is
private API and may change without notice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

__all__ = [
    "Settings",
    "__version__",
    "create_app",
]

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

    from lga.services.settings import Settings


def create_app(settings: "Settings | None" = None) -> "FastAPI":
    """Build the full FastAPI app (Studio API + A2A + MCP + static frontend)."""
    from lga.app import create_app as _create_app

    return _create_app(settings)


def __getattr__(name: str) -> Any:
    # Lazy attribute access keeps `import lga` light (SPEC §1.5-5).
    if name == "Settings":
        from lga.services.settings import Settings

        return Settings
    raise AttributeError(f"module 'lga' has no attribute {name!r}")
