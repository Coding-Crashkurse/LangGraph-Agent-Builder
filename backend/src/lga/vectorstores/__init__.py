"""Vector store abstraction (SPEC §8b).

``import lga.vectorstores`` must not import any vendor client — backends are
constructed lazily via :func:`build_provider`, and each vendor module imports
its client only inside its methods (import-linter contract).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from lga.vectorstores.base import (
    BackendExtraMissing,
    CollectionInfo,
    CollectionMissing,
    DimensionMismatch,
    Metric,
    UpsertResult,
    VectorStoreError,
    VectorStoreProvider,
    matches_filter,
)

# backend name → optional extra required (None = core / always available)
BACKEND_EXTRAS: dict[str, str | None] = {
    "local": None,
    "pgvector": "pgvector",
    "qdrant": "qdrant",
    "weaviate": "weaviate",
    "chroma": "chroma",
}

BUILTIN_BACKENDS = tuple(BACKEND_EXTRAS)


def installed_backends() -> list[str]:
    """Backends whose client extra is importable right now (for CLI/health)."""
    out = ["local"]
    checks = {
        "pgvector": "asyncpg",
        "qdrant": "qdrant_client",
        "weaviate": "weaviate",
        "chroma": "chromadb",
    }
    import importlib.util

    for backend, module in checks.items():
        if importlib.util.find_spec(module) is not None:
            out.append(backend)
    return out


def _custom_backends() -> dict[str, Any]:
    """Discover third-party backends via the ``lga.vectorstores`` entry point."""
    import importlib.metadata as md

    found: dict[str, Any] = {}
    try:
        eps = md.entry_points(group="lga.vectorstores")
    except TypeError:  # pragma: no cover - older API
        eps = md.entry_points().get("lga.vectorstores", [])  # type: ignore[attr-defined]
    for ep in eps:
        try:
            found[ep.name] = ep.load()
        except Exception:  # pragma: no cover - defensive
            continue
    return found


def build_provider(
    backend: str,
    name: str,
    params: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
) -> VectorStoreProvider:
    """Construct a provider for a named connection (SPEC §8b.1).

    Raises :class:`BackendExtraMissing` (→ E901) when the vendor extra is
    absent, with the exact ``pip install "lga[<extra>]"`` hint.
    """
    params = params or {}
    if backend == "local":
        from lga.vectorstores.local import LocalVectorStore

        root = (home or Path.home() / ".lga") / "vectors"
        return LocalVectorStore(name, root)
    if backend == "pgvector":
        from lga.vectorstores.pgvector import PgVectorStore

        return PgVectorStore(name, params)
    if backend == "qdrant":
        from lga.vectorstores.qdrant import QdrantVectorStore

        return QdrantVectorStore(name, params)
    if backend == "weaviate":
        from lga.vectorstores.weaviate import WeaviateVectorStore

        return WeaviateVectorStore(name, params)
    if backend == "chroma":
        from lga.vectorstores.chroma import ChromaVectorStore

        return ChromaVectorStore(name, params)
    custom = _custom_backends()
    if backend in custom:
        return cast("VectorStoreProvider", custom[backend](name, params))
    raise VectorStoreError(backend, f"unknown vector store backend {backend!r}")


__all__ = [
    "BACKEND_EXTRAS",
    "BUILTIN_BACKENDS",
    "BackendExtraMissing",
    "CollectionInfo",
    "CollectionMissing",
    "DimensionMismatch",
    "Metric",
    "UpsertResult",
    "VectorStoreError",
    "VectorStoreProvider",
    "build_provider",
    "installed_backends",
    "matches_filter",
]
