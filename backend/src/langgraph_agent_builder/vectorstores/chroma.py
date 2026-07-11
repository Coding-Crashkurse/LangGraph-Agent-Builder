"""Chroma backend (SPEC §8b.2) — extra ``langgraph-agent-builder[chroma]`` (chromadb).

Contract notes (see ``base.py``): the provider memoizes one client (embedded
``PersistentClient`` or ``HttpClient``; chroma exposes no close, so ``aclose()``
just drops the reference). Portable filters translate to chroma's native
``where=`` dict (single-conjunct or ``$and``-wrapped — chroma allows only one
top-level key) applied before top-k; ``raw_filter`` dicts pass through as
``where=`` verbatim. Collection metadata carries ``lga_dim`` next to
``hnsw:space`` so dim/metric survive round-trips. Default ids are the sha256
content hash (hex-truncated). Scores convert from the native distance per
metric (cosine/ip → ``1-d``, which for ip *is* the raw inner product since
chroma's ip distance is ``1-dot``; l2 is squared → ``1/(1+sqrt(d))``).
Null-valued filters are rejected (chroma metadata cannot hold nulls); delete
counts come from resolving matching ids first — best-effort under concurrent
writers.
"""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING, Any, ClassVar

from lga.sdk.ports import Document
from lga.vectorstores.base import (
    BackendExtraMissing,
    CollectionInfo,
    CollectionMissing,
    DimensionMismatch,
    Metric,
    UpsertResult,
    VectorStoreError,
    check_filter_args,
    content_hash_id,
    filter_conjuncts,
    filter_matches_nothing,
)

if TYPE_CHECKING:
    import chromadb

_SPACE = {"cosine": "cosine", "l2": "l2", "ip": "ip"}
_SCALAR = (str, int, float, bool)


def _to_score(metric: Metric, distance: float) -> float:
    if metric == "l2":  # chroma l2 distance is *squared* euclidean
        return 1.0 / (1.0 + math.sqrt(max(distance, 0.0)))
    return 1.0 - distance  # cosine: 1-d = similarity; ip: d = 1-dot → 1-d = dot


def _translate_where(flt: dict[str, Any] | None) -> dict[str, Any] | None:
    """Portable filter → chroma ``where=`` dict (one top-level key per clause)."""
    conjuncts = filter_conjuncts(flt)
    if not conjuncts:
        return None
    clauses: list[dict[str, Any]] = []
    for key, op, operand in conjuncts:
        if op == "eq":
            if not isinstance(operand, _SCALAR):
                raise VectorStoreError("chroma", f"unsupported filter value {operand!r} for chroma")
            clauses.append({key: {"$eq": operand}})
        else:
            if not all(isinstance(v, _SCALAR) for v in operand):
                raise VectorStoreError(
                    "chroma", f"unsupported filter values {operand!r} for chroma"
                )
            clauses.append({key: {"$in": list(operand)}})
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class ChromaVectorStore:
    backend: ClassVar[str] = "chroma"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self._client: chromadb.ClientAPI | None = None

    def _get_client(self) -> chromadb.ClientAPI:
        if self._client is None:
            try:
                import chromadb
            except ImportError as exc:  # pragma: no cover - needs extra
                raise BackendExtraMissing("chroma", "chroma") from exc
            mode = self.params.get("mode", "embedded")
            if mode == "http":
                self._client = chromadb.HttpClient(
                    host=self.params.get("host", "localhost"),
                    port=int(self.params.get("port", 8000)),
                )
            else:
                self._client = chromadb.PersistentClient(path=self.params.get("path", "./chroma"))
        return self._client

    async def aclose(self) -> None:
        """Chroma clients expose no close — drop the reference; next call reopens."""
        self._client = None

    def _collection(self, client: chromadb.ClientAPI, name: str) -> Any:
        try:
            return client.get_collection(name)
        except Exception as exc:
            raise CollectionMissing(self.backend, name) from exc

    async def health(self) -> None:
        def _check() -> None:
            try:
                self._get_client().heartbeat()
            except BackendExtraMissing:
                raise
            except Exception as exc:
                raise VectorStoreError("chroma", str(exc)) from exc

        await asyncio.to_thread(_check)

    async def list_collections(self) -> list[CollectionInfo]:
        def _list() -> list[CollectionInfo]:
            client = self._get_client()
            out: list[CollectionInfo] = []
            for c in client.list_collections():
                coll = client.get_collection(c.name)
                meta = dict(coll.metadata or {})
                metric = str(meta.get("hnsw:space", "cosine"))
                out.append(
                    CollectionInfo(
                        name=c.name,
                        dim=int(meta.get("lga_dim", 0) or 0),
                        metric=metric if metric in _SPACE else "cosine",  # type: ignore[arg-type]
                        count=coll.count(),
                    )
                )
            return out

        return await asyncio.to_thread(_list)

    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None:
        def _ensure() -> None:
            client = self._get_client()
            coll = client.get_or_create_collection(
                name, metadata={"hnsw:space": _SPACE.get(metric, "cosine"), "lga_dim": dim}
            )
            existing = int((coll.metadata or {}).get("lga_dim", 0) or 0)
            if existing and existing != dim:
                raise DimensionMismatch("chroma", existing, dim)

        await asyncio.to_thread(_ensure)

    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult:
        if len(docs) != len(embeddings):
            raise VectorStoreError(self.backend, "docs/embeddings length mismatch")

        def _upsert() -> list[str]:
            client = self._get_client()
            coll = self._collection(client, collection)
            dim = int((coll.metadata or {}).get("lga_dim", 0) or 0)
            for emb in embeddings:
                if dim and len(emb) != dim:
                    raise DimensionMismatch("chroma", dim, len(emb))
            ids = [str(d.metadata.get("id") or content_hash_id(d.page_content)) for d in docs]
            coll.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=[d.page_content for d in docs],
                metadatas=[d.metadata or {"_": ""} for d in docs],
            )
            return ids

        ids = await asyncio.to_thread(_upsert)
        return UpsertResult(count=len(ids), ids=ids)

    async def query(
        self,
        collection: str,
        embedding: list[float],
        k: int = 4,
        filter: dict[str, Any] | None = None,
        score_threshold: float | None = None,
        raw_filter: dict[str, Any] | None = None,
    ) -> list[Document]:
        check_filter_args(self.backend, filter, raw_filter)
        nothing = filter_matches_nothing(filter)  # chroma rejects empty $in lists
        where = None if nothing else (raw_filter or _translate_where(filter))

        def _query() -> list[Document]:
            client = self._get_client()
            coll = self._collection(client, collection)
            if nothing:
                return []
            meta = dict(coll.metadata or {})
            metric = str(meta.get("hnsw:space", "cosine"))
            metric = metric if metric in _SPACE else "cosine"
            res = coll.query(query_embeddings=[embedding], n_results=k, where=where)
            out: list[Document] = []
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            for content, doc_meta, dist in zip(docs, metas, dists, strict=False):
                metadata = dict(doc_meta or {})
                score = _to_score(metric, float(dist)) if dist is not None else None  # type: ignore[arg-type]
                if score_threshold is not None and (score or 0) < score_threshold:
                    continue
                out.append(Document(page_content=content, metadata=metadata, score=score))
            return out

        return await asyncio.to_thread(_query)

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int:
        nothing = filter_matches_nothing(filter)  # chroma rejects empty $in lists
        where = _translate_where(filter) if filter and not nothing else None

        def _delete() -> int:
            client = self._get_client()
            coll = self._collection(client, collection)
            # resolve matching ids first so the count is exact at delete time
            if ids:
                victims = list(coll.get(ids=ids).get("ids") or [])
            elif nothing:
                victims = []
            elif where is not None:
                victims = list(coll.get(where=where).get("ids") or [])
            else:
                victims = list(coll.get().get("ids") or [])
            if victims:
                coll.delete(ids=victims)
            return len(victims)

        return await asyncio.to_thread(_delete)
