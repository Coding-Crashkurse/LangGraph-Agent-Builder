"""Vector store abstraction — provider protocol & shared types (SPEC §8b.1).

One typed abstraction, named connections, backends as extras — the same
pattern as MCP servers and model providers. ``import langgraph_agent_builder`` must never import a
vendor client (import-linter contract): every backend lazy-imports its client
inside its own module and is only constructed on demand.

Cross-backend contract (pinned by ``tests/contract/test_vectorstore_contract.py``):

* **Ids** — a document's id is ``metadata["id"]`` when present, else a
  deterministic content hash (:func:`content_hash_id`). Re-ingesting the same
  documents therefore *upserts* instead of duplicating, from any process.
  Backends whose native ids must be UUIDs (qdrant, weaviate) derive them via
  :func:`content_hash_uuid` / :func:`coerce_uuid_id` — still deterministic.
* **Scores** — ``Document.score`` is normalized per metric so
  ``score_threshold`` means the same thing everywhere:
  ``cosine`` → cosine similarity (1.0 identical), ``l2`` → ``1 / (1 + d)``
  with ``d`` the euclidean distance, ``ip`` → the raw inner product.
  local and pgvector are exact; vendor backends convert from their native
  distance and note any degradation in their module docstring.
* **Filters** — the portable subset (equality, ``$eq``, ``$in``, ``$and``) is
  translated to the backend's *native* filter language and applied **before**
  top-k, so matching documents are never silently lost. Unsupported constructs
  raise :class:`VectorStoreError` (→ RT107). An empty ``$in`` matches nothing;
  a degenerate filter (``{"$and": []}``) matches everything — everywhere.
  ``raw_filter`` is passed verbatim to the vendor API (W204); backends without
  a dict-shaped native dialect (local, pgvector, weaviate) reject it with a
  clear error, and ``filter`` + ``raw_filter`` together are always an error.
* **delete()** — ``ids`` wins over ``filter``; a portable ``filter`` deletes
  the matching documents; *both omitted* deletes every document in the
  collection (the collection itself remains). The return value is the number
  of documents removed — exact on local/pgvector, count-before-delete
  best-effort on vendor backends (racy under concurrent writers).

Built-in providers additionally own a lazily-initialized client/pool with a
one-time schema-ensure memo and expose ``aclose()``; the protocol stays the
SPEC §8b.1 shape, so ``aclose`` is invoked via duck-typing
(``services/vectorstores.py``) and custom backends need not implement it.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from langgraph_agent_builder.errors import LabError
from langgraph_agent_builder.sdk.ports import Document

Metric = Literal["cosine", "l2", "ip"]


class CollectionInfo(BaseModel):
    name: str
    dim: int
    metric: Metric = "cosine"
    count: int = 0


class UpsertResult(BaseModel):
    count: int
    ids: list[str] = []


class VectorStoreError(LabError):
    """Backend failure → surfaced as RT107 at runtime / E902 at deep-validate."""

    def __init__(self, backend: str, detail: str) -> None:
        super().__init__(f"[{backend}] {detail}")
        self.backend = backend
        self.detail = detail


class BackendExtraMissing(VectorStoreError):
    """The backend's optional extra is not installed (E901)."""

    def __init__(self, backend: str, extra: str) -> None:
        super().__init__(backend, f'requires: pip install "langgraph-agent-builder[{extra}]"')
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
    keys. Backends translate natively; unsupported constructs raise
    ``VectorStoreError``. ``raw_filter`` passes a backend-specific filter
    verbatim to the vendor API (SPEC §8b.1, W204). See the module docstring for
    the full cross-backend contract (ids, scores, delete semantics).
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
        raw_filter: dict[str, Any] | None = None,
    ) -> list[Document]: ...
    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int: ...


# --------------------------------------------------------------------------- ids
def content_hash_id(text: str) -> str:
    """Deterministic default document id: sha256 of the content, hex-truncated.

    Unlike ``hash()`` (salted per process) or ``uuid4()``, re-ingesting the same
    document from any process yields the same id, so periodic re-seeds upsert
    instead of duplicating rows. Order-independent by construction.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def content_hash_uuid(text: str) -> str:
    """:func:`content_hash_id` in UUID form, for backends whose ids must be UUIDs."""
    return str(uuid.UUID(bytes=hashlib.sha256(text.encode("utf-8")).digest()[:16]))


def coerce_uuid_id(value: str) -> str:
    """Pass valid UUIDs through; map any other id deterministically to a UUID.

    Backends whose native ids must be UUIDs (qdrant, weaviate) use this for
    user-supplied ``metadata["id"]`` values so upsert/delete round-trip on the
    same derived id.
    """
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return content_hash_uuid(f"id:{value}")


# --------------------------------------------------------------------------- portable filter
def matches_filter(metadata: dict[str, Any], flt: dict[str, Any] | None) -> bool:
    """Evaluate the portable filter subset (equality, ``$in``, ``$and``).

    Unsupported operators raise ``VectorStoreError`` so backends and the local
    engine share one semantics (SPEC §8b.1). This is the *reference*
    implementation — backends translate natively via :func:`filter_conjuncts`
    and only fall back to this for constructs their engine cannot address.
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


FilterOp = Literal["eq", "in"]


def filter_conjuncts(flt: dict[str, Any] | None) -> list[tuple[str, FilterOp, Any]]:
    """Flatten the portable filter into ``(key, op, operand)`` conjuncts.

    The portable subset is purely conjunctive (``$and`` of equality/``$in``),
    so backends can translate the flat list into their native filter language
    and apply it *before* top-k. Raises :class:`VectorStoreError` on
    unsupported operators — same semantics as :func:`matches_filter`.
    """
    out: list[tuple[str, FilterOp, Any]] = []
    if not flt:
        return out
    for key, cond in flt.items():
        if key == "$and":
            for sub in cond:
                out.extend(filter_conjuncts(sub))
            continue
        if key.startswith("$"):
            raise VectorStoreError("filter", f"unsupported operator {key!r}")
        if isinstance(cond, dict):
            for op, operand in cond.items():
                if op == "$in":
                    out.append((key, "in", list(operand)))
                elif op == "$eq":
                    out.append((key, "eq", operand))
                else:
                    raise VectorStoreError("filter", f"unsupported operator {op!r}")
        else:
            out.append((key, "eq", cond))
    return out


def filter_matches_nothing(flt: dict[str, Any] | None) -> bool:
    """True when the portable filter can never match (it has an empty ``$in``).

    Backends whose native engine cannot express a never-matching condition
    (qdrant treats an empty ``should`` as no constraint; weaviate/chroma reject
    empty ``contains_any``/``$in`` lists) short-circuit on this — query returns
    no documents, delete removes none — instead of translating.
    """
    return any(op == "in" and not operand for _, op, operand in filter_conjuncts(flt))


def check_filter_args(
    backend: str, filter: dict[str, Any] | None, raw_filter: dict[str, Any] | None
) -> None:
    """Enforce the shared query contract: ``filter`` and ``raw_filter`` are exclusive."""
    if filter and raw_filter:
        raise VectorStoreError(backend, "`filter` and `raw_filter` are mutually exclusive")
