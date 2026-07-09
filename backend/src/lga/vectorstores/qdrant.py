"""Qdrant backend (SPEC §8b.2) — extra ``lga[qdrant]``, lazy client import."""

from __future__ import annotations

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
    import qdrant_client

_METRICS = {"cosine": "Cosine", "l2": "Euclid", "ip": "Dot"}


def _client(params: dict[str, Any]) -> qdrant_client.AsyncQdrantClient:
    try:
        from qdrant_client import AsyncQdrantClient
    except ImportError as exc:  # pragma: no cover - needs extra
        raise BackendExtraMissing("qdrant", "qdrant") from exc
    return AsyncQdrantClient(
        url=params.get("url", "http://localhost:6333"),
        api_key=params.get("api_key") or None,
        prefer_grpc=bool(params.get("grpc", False)),
    )


class QdrantVectorStore:
    backend: ClassVar[str] = "qdrant"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params

    async def health(self) -> None:
        client = _client(self.params)
        try:
            await client.get_collections()
        except BackendExtraMissing:
            raise
        except Exception as exc:
            raise VectorStoreError(self.backend, str(exc)) from exc
        finally:
            await client.close()

    async def list_collections(self) -> list[CollectionInfo]:
        client = _client(self.params)
        try:
            resp = await client.get_collections()
            out: list[CollectionInfo] = []
            for c in resp.collections:
                info = await client.get_collection(c.name)
                vectors = info.config.params.vectors
                dim = getattr(vectors, "size", 0) or 0
                out.append(CollectionInfo(name=c.name, dim=dim, count=info.points_count or 0))
            return out
        finally:
            await client.close()

    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None:
        from qdrant_client import models

        client = _client(self.params)
        try:
            if await client.collection_exists(name):
                return
            await client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=dim, distance=getattr(models.Distance, _METRICS[metric].upper())
                ),
            )
        finally:
            await client.close()

    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult:
        import uuid

        from qdrant_client import models

        client = _client(self.params)
        try:
            points = []
            ids: list[str] = []
            for doc, emb in zip(docs, embeddings, strict=True):
                pid = str(doc.metadata.get("id") or uuid.uuid4())
                ids.append(pid)
                points.append(
                    models.PointStruct(
                        id=pid,
                        vector=emb,
                        payload={"page_content": doc.page_content, **doc.metadata},
                    )
                )
            await client.upsert(collection_name=collection, points=points)
            return UpsertResult(count=len(ids), ids=ids)
        finally:
            await client.close()

    async def query(
        self,
        collection: str,
        embedding: list[float],
        k: int = 4,
        filter: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[Document]:
        client = _client(self.params)
        try:
            if not await client.collection_exists(collection):
                raise CollectionMissing(self.backend, collection)
            hits = await client.search(
                collection_name=collection,
                query_vector=embedding,
                limit=k,
                score_threshold=score_threshold,
                with_payload=True,
            )
            out: list[Document] = []
            for h in hits:
                payload = dict(h.payload or {})
                content = payload.pop("page_content", "")
                if not matches_filter(payload, filter):
                    continue
                out.append(Document(page_content=content, metadata=payload, score=h.score))
            return out
        finally:
            await client.close()

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int:
        from qdrant_client import models

        client = _client(self.params)
        try:
            if ids:
                await client.delete(
                    collection_name=collection,
                    points_selector=models.PointIdsList(points=ids),
                )
                return len(ids)
            if filter is None:
                await client.delete(
                    collection_name=collection,
                    points_selector=models.FilterSelector(filter=models.Filter()),
                )
            return 0
        finally:
            await client.close()
