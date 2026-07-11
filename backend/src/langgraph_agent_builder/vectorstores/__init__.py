"""Vector store abstraction (SPEC §8b).

``import lga.vectorstores`` must not import any vendor client — backends are
constructed lazily via :func:`build_provider`, and each vendor module imports
its client only inside its methods (import-linter contract).

One registry drives everything: the pip extra (E901 hints), the probe module
(:func:`installed_backends`) and the lazy factory (:func:`build_provider`)
live in a single ``_REGISTRY`` entry per backend, merged with third-party
backends discovered via the ``lga.vectorstores`` entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from lga.vectorstores.base import (
    BackendExtraMissing,
    CollectionInfo,
    CollectionMissing,
    DimensionMismatch,
    Metric,
    UpsertResult,
    VectorStoreError,
    VectorStoreProvider,
    content_hash_id,
    content_hash_uuid,
    filter_conjuncts,
    matches_filter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    ProviderFactory = Callable[[str, dict[str, Any], Path | None], VectorStoreProvider]


def _local(name: str, params: dict[str, Any], home: Path | None) -> VectorStoreProvider:
    from lga.vectorstores.local import LocalVectorStore

    root = (home or Path.home() / ".lga") / "vectors"
    return LocalVectorStore(name, root)


def _pgvector(name: str, params: dict[str, Any], home: Path | None) -> VectorStoreProvider:
    from lga.vectorstores.pgvector import PgVectorStore

    return PgVectorStore(name, params)


def _qdrant(name: str, params: dict[str, Any], home: Path | None) -> VectorStoreProvider:
    from lga.vectorstores.qdrant import QdrantVectorStore

    return QdrantVectorStore(name, params)


def _weaviate(name: str, params: dict[str, Any], home: Path | None) -> VectorStoreProvider:
    from lga.vectorstores.weaviate import WeaviateVectorStore

    return WeaviateVectorStore(name, params)


def _chroma(name: str, params: dict[str, Any], home: Path | None) -> VectorStoreProvider:
    from lga.vectorstores.chroma import ChromaVectorStore

    return ChromaVectorStore(name, params)


class _Backend(NamedTuple):
    extra: str | None  # pip extra required (None = core / always available)
    probe: str | None  # importable client module (None = always installed)
    factory: ProviderFactory


_REGISTRY: dict[str, _Backend] = {
    "local": _Backend(None, None, _local),
    "pgvector": _Backend("pgvector", "asyncpg", _pgvector),
    "qdrant": _Backend("qdrant", "qdrant_client", _qdrant),
    "weaviate": _Backend("weaviate", "weaviate", _weaviate),
    "chroma": _Backend("chroma", "chromadb", _chroma),
}

# backend name → optional extra required (None = core / always available)
BACKEND_EXTRAS: dict[str, str | None] = {name: spec.extra for name, spec in _REGISTRY.items()}

BUILTIN_BACKENDS = tuple(_REGISTRY)


def installed_backends() -> list[str]:
    """Backends usable right now (for CLI/health) — built-ins whose client
    extra is importable plus entry-point-registered custom backends."""
    import importlib.util

    out = [
        name
        for name, spec in _REGISTRY.items()
        if spec.probe is None or importlib.util.find_spec(spec.probe) is not None
    ]
    out.extend(name for name in _custom_backends() if name not in _REGISTRY)
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
    absent, with the exact ``pip install "langgraph-agent-builder[<extra>]"`` hint.
    """
    params = params or {}
    spec = _REGISTRY.get(backend)
    if spec is not None:
        return spec.factory(name, params, home)
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
    "content_hash_id",
    "content_hash_uuid",
    "filter_conjuncts",
    "installed_backends",
    "matches_filter",
]
