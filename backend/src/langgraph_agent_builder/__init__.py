"""LangGraph Agent Builder — LangGraph-native visual agent builder.

Public, semver-stable surface (SPEC §2.7). Everything not exported here is
private API and may change without notice.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version
from typing import TYPE_CHECKING, Any

try:
    __version__ = _version("langgraph-agent-builder")
except PackageNotFoundError:  # pragma: no cover - running from a source checkout
    __version__ = "0.0.1"

__all__ = [
    "Settings",
    "__version__",
    "create_app",
]

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

    from langgraph_agent_builder.services.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the full FastAPI app (Studio API + A2A + MCP + static frontend)."""
    from langgraph_agent_builder.app import create_app as _create_app

    return _create_app(settings)


def __getattr__(name: str) -> Any:
    # Lazy attribute access keeps `import langgraph_agent_builder` light (SPEC §1.5-5).
    if name == "Settings":
        from langgraph_agent_builder.services.settings import Settings

        return Settings
    raise AttributeError(f"module 'langgraph_agent_builder' has no attribute {name!r}")
