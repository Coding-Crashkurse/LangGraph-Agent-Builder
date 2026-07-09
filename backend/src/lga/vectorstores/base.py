"""Vector store abstraction — provider protocol & shared types (SPEC §8b.1).

One typed abstraction, named connections, backends as extras — the same
pattern as MCP servers and model providers. ``import lga`` must never import a
vendor client (import-linter contract): every backend lazy-imports its client
inside its own module and is only constructed on demand.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from lga.errors import LgaError
from lga.sdk.ports import Document

Metric = Literal["cosine", "l2", "ip"]


class CollectionInfo(BaseModel):
    name: str
    dim: int
    metric: Metric = "cosine"
    count: int = 0


class UpsertResult(BaseModel):
    count: int
    ids: list[str] = []


class VectorStoreError(LgaError):
    """Backend failure → surfaced as RT107 at runtime / E902 at deep-validate."""

    def __init__(self, backend: str, detail: str) -> None:
        super().__init__(f"[{backend}] {detail}")
        self.backend = backend
        self.detail = detail


class BackendExtraMissing(VectorStoreError):
    """The backend's optional extra is not installed (E901)."""

    def __init__(self, backend: str, extra: str) -> None:
        super().__init__(backend, f'requires: pip install "lga[{extra}]"')
        self.extra = extra


class CollectionMissing(VectorStoreError):
    """Referenced collection does not exist (E903)."""

    def __init__(self, backend: str, collection: str) -> None:
        super().__init__(backend, f"collection {collection!r} does not exist")
        self.collection = collection


class DimensionMismatch(VectorStoreError):
    """Collection dim ≠ embedding dim (E904)."""

    def __init__(self, backend: str, expected: int, got: int) -> None:
        super().__init__(backend, f"embedding dim {got} ≠ collection dim {expected}")
        self.expected = expected
        self.got = got


@runtime_checkable
class VectorStoreProvider(Protocol):
    """A named connection to a vector backend (SPEC §8b.1).

    ``filter`` uses a portable subset — equality, ``$in``, ``$and`` on metadata
    keys. Backends translate; unsupported constructs raise ``VectorStoreError``.
    """

    backend: ClassVar[str]

    async def health(self) -> None: ...  # raises VectorStoreError → E902
    async def list_collections(self) -> list[CollectionInfo]: ...
    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None: ...
    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult: ...
    async def query(
        self,
        collection: str,
        embedding: list[float],
        k: int = 4,
        filter: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[Document]: ...
    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int: ...


# --------------------------------------------------------------------------- portable filter
def matches_filter(metadata: dict[str, Any], flt: dict[str, Any] | None) -> bool:
    """Evaluate the portable filter subset (equality, ``$in``, ``$and``).

    Unsupported operators raise ``VectorStoreError`` so backends and the local
    engine share one semantics (SPEC §8b.1).
    """
    if not flt:
        return True
    for key, cond in flt.items():
        if key == "$and":
            if not all(matches_filter(metadata, sub) for sub in cond):
                return False
            continue
        if key.startswith("$"):
            raise VectorStoreError("filter", f"unsupported operator {key!r}")
        value = metadata.get(key)
        if isinstance(cond, dict):
            for op, operand in cond.items():
                if op == "$in":
                    if value not in operand:
                        return False
                elif op == "$eq":
                    if value != operand:
                        return False
                else:
                    raise VectorStoreError("filter", f"unsupported operator {op!r}")
        elif value != cond:
            return False
    return True
