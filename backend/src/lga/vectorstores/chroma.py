"""Chroma backend (SPEC §8b.2) — extra ``lga[chroma]`` (chromadb)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

from lga.sdk.ports import Document
from lga.vectorstores.base import (
    BackendExtraMissing,
    CollectionInfo,
    CollectionMissing,
    Metric,
    UpsertResult,
    VectorStoreError,
    matches_filter,
)

if TYPE_CHECKING:
    import chromadb

_SPACE = {"cosine": "cosine", "l2": "l2", "ip": "ip"}


def _client(params: dict[str, Any]) -> chromadb.ClientAPI:
    try:
        import chromadb
    except ImportError as exc:  # pragma: no cover - needs extra
        raise BackendExtraMissing("chroma", "chroma") from exc
    mode = params.get("mode", "embedded")
    if mode == "http":
        return chromadb.HttpClient(
            host=params.get("host", "localhost"), port=int(params.get("port", 8000))
        )
    return chromadb.PersistentClient(path=params.get("path", "./chroma"))


class ChromaVectorStore:
    backend: ClassVar[str] = "chroma"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params

    async def health(self) -> None:
        def _check() -> None:
            client = _client(self.params)
            try:
                client.heartbeat()
            except BackendExtraMissing:
                raise
            except Exception as exc:
                raise VectorStoreError("chroma", str(exc)) from exc

        await asyncio.to_thread(_check)

    async def list_collections(self) -> list[CollectionInfo]:
        def _list() -> list[CollectionInfo]:
            client = _client(self.params)
            out: list[CollectionInfo] = []
            for c in client.list_collections():
                coll = client.get_collection(c.name)
                out.append(CollectionInfo(name=c.name, dim=0, count=coll.count()))
            return out

        return await asyncio.to_thread(_list)

    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None:
        def _ensure() -> None:
            client = _client(self.params)
            client.get_or_create_collection(
                name, metadata={"hnsw:space": _SPACE.get(metric, "cosine")}
            )

        await asyncio.to_thread(_ensure)

    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult:
        import uuid

        def _upsert() -> list[str]:
            client = _client(self.params)
            coll = client.get_or_create_collection(collection)
            ids = [str(d.metadata.get("id") or uuid.uuid4()) for d in docs]
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
    ) -> list[Document]:
        def _query() -> list[Document]:
            client = _client(self.params)
            try:
                coll = client.get_collection(collection)
            except Exception as exc:
                raise CollectionMissing("chroma", collection) from exc
            res = coll.query(query_embeddings=[embedding], n_results=k)
            out: list[Document] = []
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            dists = res.get("distances", [[]])[0]
            for content, meta, dist in zip(docs, metas, dists, strict=False):
                metadata = dict(meta or {})
                if not matches_filter(metadata, filter):
                    continue
                score = 1.0 - dist if dist is not None else None
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
        def _delete() -> int:
            client = _client(self.params)
            coll = client.get_collection(collection)
            before = coll.count()
            coll.delete(ids=ids, where=filter)
            return int(before - coll.count())

        return await asyncio.to_thread(_delete)
