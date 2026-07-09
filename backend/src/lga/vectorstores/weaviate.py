"""Weaviate backend (SPEC §8b.2) — extra ``lga[weaviate]`` (weaviate-client v4)."""

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
    import weaviate


def _connect(params: dict[str, Any]) -> weaviate.WeaviateClient:
    try:
        import weaviate
    except ImportError as exc:  # pragma: no cover - needs extra
        raise BackendExtraMissing("weaviate", "weaviate") from exc
    url = params.get("url", "http://localhost:8080")
    api_key = params.get("api_key")
    auth = None
    if api_key:
        from weaviate.auth import AuthApiKey

        auth = AuthApiKey(api_key)
    return weaviate.connect_to_custom(
        http_host=url.split("://")[-1].split(":")[0],
        http_port=int(url.rsplit(":", 1)[-1]) if ":" in url.split("://")[-1] else 8080,
        http_secure=url.startswith("https"),
        grpc_host=url.split("://")[-1].split(":")[0],
        grpc_port=50051,
        grpc_secure=url.startswith("https"),
        auth_credentials=auth,
    )


def _cname(name: str) -> str:
    return name[:1].upper() + name[1:]


class WeaviateVectorStore:
    backend: ClassVar[str] = "weaviate"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params

    async def health(self) -> None:
        import asyncio

        def _check() -> None:
            client = _connect(self.params)
            try:
                if not client.is_ready():
                    raise VectorStoreError("weaviate", "not ready")
            finally:
                client.close()

        await asyncio.to_thread(_check)

    async def list_collections(self) -> list[CollectionInfo]:
        import asyncio

        def _list() -> list[CollectionInfo]:
            client = _connect(self.params)
            try:
                out: list[CollectionInfo] = []
                for name in client.collections.list_all():
                    coll = client.collections.get(name)
                    count = coll.aggregate.over_all(total_count=True).total_count or 0
                    out.append(CollectionInfo(name=name, dim=0, count=count))
                return out
            finally:
                client.close()

        return await asyncio.to_thread(_list)

    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None:
        import asyncio

        def _ensure() -> None:
            import weaviate.classes.config as wc

            client = _connect(self.params)
            try:
                if client.collections.exists(_cname(name)):
                    return
                client.collections.create(
                    _cname(name),
                    vectorizer_config=wc.Configure.Vectorizer.none(),
                    properties=[wc.Property(name="page_content", data_type=wc.DataType.TEXT)],
                )
            finally:
                client.close()

        await asyncio.to_thread(_ensure)

    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult:
        import asyncio
        import uuid

        def _upsert() -> list[str]:
            client = _connect(self.params)
            try:
                coll = client.collections.get(_cname(collection))
                ids: list[str] = []
                with coll.batch.dynamic() as batch:
                    for doc, emb in zip(docs, embeddings, strict=True):
                        oid = str(doc.metadata.get("id") or uuid.uuid4())
                        ids.append(oid)
                        batch.add_object(
                            properties={"page_content": doc.page_content, **doc.metadata},
                            vector=emb,
                            uuid=oid,
                        )
                return ids
            finally:
                client.close()

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
        import asyncio

        def _query() -> list[Document]:
            client = _connect(self.params)
            try:
                if not client.collections.exists(_cname(collection)):
                    raise CollectionMissing("weaviate", collection)
                coll = client.collections.get(_cname(collection))
                res = coll.query.near_vector(
                    near_vector=embedding, limit=k, return_metadata=["distance"]
                )
                out: list[Document] = []
                for obj in res.objects:
                    props = dict(obj.properties)
                    content = props.pop("page_content", "")
                    if not matches_filter(props, filter):
                        continue
                    dist = getattr(obj.metadata, "distance", None)
                    score = 1.0 - dist if dist is not None else None
                    if score_threshold is not None and (score or 0) < score_threshold:
                        continue
                    out.append(Document(page_content=content, metadata=props, score=score))
                return out
            finally:
                client.close()

        return await asyncio.to_thread(_query)

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int:
        import asyncio

        def _delete() -> int:
            client = _connect(self.params)
            try:
                coll = client.collections.get(_cname(collection))
                deleted = 0
                for oid in ids or []:
                    coll.data.delete_by_id(oid)
                    deleted += 1
                return deleted
            finally:
                client.close()

        return await asyncio.to_thread(_delete)
