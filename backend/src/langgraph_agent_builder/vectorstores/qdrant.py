"""Qdrant backend (SPEC §8b.2) — extra ``langgraph-agent-builder[qdrant]``, lazy client import.

Contract notes (see ``base.py``): the provider memoizes one ``AsyncQdrantClient``
(``aclose()`` releases it). Connection params: ``url``/``api_key``/``grpc``, or
``location``/``path`` for qdrant's in-process local mode (used by the contract
suite). Portable filters translate to native ``models.Filter`` conditions
applied server-side before top-k; ``raw_filter`` dicts are validated into a
native ``models.Filter`` verbatim. Qdrant point ids must be UUIDs or ints, so
default ids are the sha256 content hash in UUID form and non-UUID
``metadata["id"]`` values are mapped deterministically via ``coerce_uuid_id``
(upsert/delete round-trip on the same derived id). Scores: qdrant returns
cosine similarity / dot product natively (contract-exact); for l2 collections
it returns the *distance*, converted to ``1/(1+d)`` here with the threshold
applied client-side. Delete counts are count-before-delete — best-effort under
concurrent writers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from langgraph_agent_builder.sdk.ports import Document
from langgraph_agent_builder.vectorstores.base import (
    BackendExtraMissing,
    CollectionInfo,
    CollectionMissing,
    DimensionMismatch,
    Metric,
    UpsertResult,
    VectorStoreError,
    check_filter_args,
    coerce_uuid_id,
    content_hash_uuid,
    filter_conjuncts,
    filter_matches_nothing,
)

if TYPE_CHECKING:
    import qdrant_client

_METRICS = {"cosine": "Cosine", "l2": "Euclid", "ip": "Dot"}
_METRICS_BACK: dict[str, Metric] = {"Cosine": "cosine", "Euclid": "l2", "Dot": "ip"}


def _distance_value(vectors: Any) -> str:
    distance = getattr(vectors, "distance", None)
    return str(getattr(distance, "value", distance) or "Cosine")


def _translate_filter(flt: dict[str, Any] | None) -> Any:
    """Portable filter → native ``models.Filter`` (applied before top-k)."""
    from qdrant_client import models

    def eq_condition(key: str, value: Any) -> Any:
        if value is None:
            # matches missing keys and nulls — closest to the reference semantics
            return models.IsEmptyCondition(is_empty=models.PayloadField(key=key))
        if isinstance(value, bool | int | str):
            return models.FieldCondition(key=key, match=models.MatchValue(value=value))
        if isinstance(value, float):
            return models.FieldCondition(key=key, range=models.Range(gte=value, lte=value))
        raise VectorStoreError("filter", f"unsupported filter value {value!r} for qdrant")

    conjuncts = filter_conjuncts(flt)
    if not conjuncts:
        return None
    must: list[Any] = []
    for key, op, operand in conjuncts:
        if op == "eq":
            must.append(eq_condition(key, operand))
        else:
            must.append(models.Filter(should=[eq_condition(key, v) for v in operand]))
    return models.Filter(must=must)


class QdrantVectorStore:
    backend: ClassVar[str] = "qdrant"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self._client: qdrant_client.AsyncQdrantClient | None = None
        self._metric_cache: dict[str, Metric] = {}

    def _get_client(self) -> qdrant_client.AsyncQdrantClient:
        if self._client is None:
            try:
                from qdrant_client import AsyncQdrantClient
            except ImportError as exc:  # pragma: no cover - needs extra
                raise BackendExtraMissing("qdrant", "qdrant") from exc
            if self.params.get("location"):
                self._client = AsyncQdrantClient(location=str(self.params["location"]))
            elif self.params.get("path"):
                self._client = AsyncQdrantClient(path=str(self.params["path"]))
            else:
                self._client = AsyncQdrantClient(
                    url=self.params.get("url", "http://localhost:6333"),
                    api_key=self.params.get("api_key") or None,
                    prefer_grpc=bool(self.params.get("grpc", False)),
                )
        return self._client

    async def aclose(self) -> None:
        """Release the client; a later call lazily reconnects."""
        if self._client is not None:
            client, self._client = self._client, None
            await client.close()

    async def _metric(self, collection: str) -> Metric:
        metric = self._metric_cache.get(collection)
        if metric is None:
            info = await self._get_client().get_collection(collection)
            value = _distance_value(info.config.params.vectors)
            metric = _METRICS_BACK.get(value, "cosine")
            self._metric_cache[collection] = metric
        return metric

    async def health(self) -> None:
        try:
            await self._get_client().get_collections()
        except BackendExtraMissing:
            raise
        except Exception as exc:
            raise VectorStoreError(self.backend, str(exc)) from exc

    async def list_collections(self) -> list[CollectionInfo]:
        client = self._get_client()
        resp = await client.get_collections()
        out: list[CollectionInfo] = []
        for c in resp.collections:
            info = await client.get_collection(c.name)
            vectors = info.config.params.vectors
            dim = getattr(vectors, "size", 0) or 0
            metric = _METRICS_BACK.get(_distance_value(vectors), "cosine")
            out.append(
                CollectionInfo(name=c.name, dim=dim, metric=metric, count=info.points_count or 0)
            )
        return out

    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None:
        from qdrant_client import models

        client = self._get_client()
        if await client.collection_exists(name):
            info = await client.get_collection(name)
            existing = getattr(info.config.params.vectors, "size", 0) or 0
            if existing and existing != dim:
                raise DimensionMismatch(self.backend, existing, dim)
            return
        await client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=dim, distance=getattr(models.Distance, _METRICS[metric].upper())
            ),
        )

    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult:
        from qdrant_client import models

        client = self._get_client()
        if not await client.collection_exists(collection):
            raise CollectionMissing(self.backend, collection)
        points = []
        ids: list[str] = []
        for doc, emb in zip(docs, embeddings, strict=True):
            raw_id = doc.metadata.get("id")
            pid = coerce_uuid_id(str(raw_id)) if raw_id else content_hash_uuid(doc.page_content)
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

    async def query(
        self,
        collection: str,
        embedding: list[float],
        k: int = 4,
        filter: dict[str, Any] | None = None,
        score_threshold: float | None = None,
        raw_filter: dict[str, Any] | None = None,
    ) -> list[Document]:
        from qdrant_client import models

        check_filter_args(self.backend, filter, raw_filter)
        client = self._get_client()
        if not await client.collection_exists(collection):
            raise CollectionMissing(self.backend, collection)
        if filter_matches_nothing(filter):  # empty $in — qdrant can't express it
            return []
        if raw_filter:
            try:
                query_filter = models.Filter.model_validate(raw_filter)
            except Exception as exc:
                raise VectorStoreError(self.backend, f"invalid raw_filter: {exc}") from exc
        else:
            query_filter = _translate_filter(filter)
        metric = await self._metric(collection)
        # for l2 qdrant scores are *distances*; converted client-side, so the
        # native threshold can only be pushed down for cosine/ip
        native_threshold = score_threshold if metric != "l2" else None
        hits = await client.search(
            collection_name=collection,
            query_vector=embedding,
            query_filter=query_filter,
            limit=k,
            score_threshold=native_threshold,
            with_payload=True,
        )
        out: list[Document] = []
        for h in hits:
            payload = dict(h.payload or {})
            content = str(payload.pop("page_content", ""))
            score = float(h.score) if metric != "l2" else 1.0 / (1.0 + float(h.score))
            if score_threshold is not None and score < score_threshold:
                continue
            out.append(Document(page_content=content, metadata=payload, score=score))
        return out

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int:
        from qdrant_client import models

        client = self._get_client()
        if not await client.collection_exists(collection):
            raise CollectionMissing(self.backend, collection)
        if ids:
            mapped = [coerce_uuid_id(i) for i in ids]
            existing = await client.retrieve(
                collection, ids=cast("list[Any]", mapped), with_payload=False, with_vectors=False
            )
            await client.delete(
                collection_name=collection,
                points_selector=models.PointIdsList(points=cast("list[Any]", mapped)),
            )
            return len(existing)
        if filter_matches_nothing(filter):  # empty $in must not fall through to match-all
            return 0
        query_filter = (_translate_filter(filter) if filter else None) or models.Filter()
        count = (await client.count(collection, count_filter=query_filter, exact=True)).count
        await client.delete(
            collection_name=collection,
            points_selector=models.FilterSelector(filter=query_filter),
        )
        return int(count)
