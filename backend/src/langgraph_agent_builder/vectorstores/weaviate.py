"""Weaviate backend (SPEC §8b.2) — extra ``langgraph-agent-builder[weaviate]``
(weaviate-client v4).

Contract notes (see ``base.py``): the provider memoizes one sync client
(driven via ``asyncio.to_thread``; ``aclose()`` releases it). Connection
params: ``url`` (parsed with ``urlsplit``; scheme-aware default ports 443/80),
``api_key``, and ``grpc_host``/``grpc_port``/``grpc_secure`` overrides.

Weaviate capitalizes collection names, so lga names must match
``[a-z][A-Za-z0-9_]*`` to round-trip (``docs`` ↔ ``Docs``); anything else is
rejected at :meth:`ensure_collection` with a clear error, and
``list_collections`` translates back. The collection ``description`` field
carries ``lga:dim=<n>;metric=<m>`` so dim/metric survive round-trips (weaviate
itself has no collection metadata). Object ids must be UUIDs: default ids are
the sha256 content hash in UUID form, non-UUID ``metadata["id"]`` values map
deterministically via ``coerce_uuid_id``. Portable filters translate to native
``Filter`` objects applied before top-k; null-valued filters and ``raw_filter``
are rejected with clear errors (v4 filters are builder objects, not dicts).
Scores convert from the native distance per metric (cosine → ``1-d``,
l2-squared → ``1/(1+sqrt(d))``, dot → ``-d``); delete counts come from
``delete_many`` responses — best-effort under concurrent writers.
"""

from __future__ import annotations

import math
import re
import threading
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlsplit

from lga.sdk.ports import Document
from lga.vectorstores.base import (
    BackendExtraMissing,
    CollectionInfo,
    CollectionMissing,
    DimensionMismatch,
    Metric,
    UpsertResult,
    VectorStoreError,
    coerce_uuid_id,
    content_hash_uuid,
    filter_conjuncts,
    filter_matches_nothing,
)

if TYPE_CHECKING:
    import weaviate

_NAME = re.compile(r"^[a-z][A-Za-z0-9_]*$")
_DESC = re.compile(r"lga:dim=(\d+);metric=(\w+)")
_DELETE_CHUNK = 500


def _endpoints(params: dict[str, Any]) -> tuple[str, int, bool, str, int, bool]:
    """Resolve http/grpc endpoints from params with scheme-aware defaults."""
    url = str(params.get("url", "http://localhost:8080"))
    parts = urlsplit(url if "://" in url else f"http://{url}")
    secure = parts.scheme == "https"
    host = parts.hostname or "localhost"
    port = parts.port or (443 if secure else 80)
    grpc_host = str(params.get("grpc_host") or host)
    grpc_port = int(params.get("grpc_port") or 50051)
    grpc_secure = bool(params.get("grpc_secure", secure))
    return host, port, secure, grpc_host, grpc_port, grpc_secure


def _cname(name: str) -> str:
    """lga name → Weaviate collection name; reject names that can't round-trip."""
    if not _NAME.match(name):
        raise VectorStoreError(
            "weaviate",
            f"collection name {name!r} cannot round-trip through Weaviate — "
            "use [a-z][A-Za-z0-9_]* (Weaviate capitalizes the first letter)",
        )
    return name[0].upper() + name[1:]


def _from_cname(cname: str) -> str:
    return cname[0].lower() + cname[1:] if cname else cname


def _parse_desc(description: str | None) -> tuple[int, Metric]:
    match = _DESC.search(description or "")
    if not match:
        return 0, "cosine"
    metric = match.group(2)
    return int(match.group(1)), metric if metric in ("cosine", "l2", "ip") else "cosine"  # type: ignore[return-value]


def _to_score(metric: Metric, distance: float) -> float:
    if metric == "l2":  # weaviate l2 distance is *squared* euclidean
        return 1.0 / (1.0 + math.sqrt(max(distance, 0.0)))
    if metric == "ip":  # weaviate dot distance is the negated inner product
        return -distance
    return 1.0 - distance


def _translate_filter(flt: dict[str, Any] | None) -> Any:
    """Portable filter → native ``Filter`` objects (applied before top-k)."""
    from weaviate.classes.query import Filter

    conjuncts = filter_conjuncts(flt)
    if not conjuncts:
        return None
    parts: list[Any] = []
    for key, op, operand in conjuncts:
        if op == "eq":
            if operand is None:
                raise VectorStoreError(
                    "weaviate", "null-valued filters are not supported by the weaviate backend"
                )
            parts.append(Filter.by_property(key).equal(operand))
        else:
            if any(v is None for v in operand):
                raise VectorStoreError(
                    "weaviate", "null-valued filters are not supported by the weaviate backend"
                )
            parts.append(Filter.by_property(key).contains_any(list(operand)))
    return Filter.all_of(parts) if len(parts) > 1 else parts[0]


class WeaviateVectorStore:
    backend: ClassVar[str] = "weaviate"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self._client: weaviate.WeaviateClient | None = None
        # sync client shared across to_thread workers — serialize creation/use
        self._lock = threading.Lock()

    def _connect(self) -> weaviate.WeaviateClient:
        try:
            import weaviate
        except ImportError as exc:  # pragma: no cover - needs extra
            raise BackendExtraMissing("weaviate", "weaviate") from exc
        if self._client is None:
            api_key = self.params.get("api_key")
            auth = None
            if api_key:
                from weaviate.auth import AuthApiKey

                auth = AuthApiKey(api_key)
            host, port, secure, grpc_host, grpc_port, grpc_secure = _endpoints(self.params)
            self._client = weaviate.connect_to_custom(
                http_host=host,
                http_port=port,
                http_secure=secure,
                grpc_host=grpc_host,
                grpc_port=grpc_port,
                grpc_secure=grpc_secure,
                auth_credentials=auth,
            )
        return self._client

    async def aclose(self) -> None:
        """Release the client; a later call lazily reconnects."""
        import asyncio

        def _close() -> None:
            with self._lock:
                if self._client is not None:
                    client, self._client = self._client, None
                    client.close()

        await asyncio.to_thread(_close)

    async def health(self) -> None:
        import asyncio

        def _check() -> None:
            with self._lock:
                client = self._connect()
                if not client.is_ready():
                    raise VectorStoreError("weaviate", "not ready")

        await asyncio.to_thread(_check)

    async def list_collections(self) -> list[CollectionInfo]:
        import asyncio

        def _list() -> list[CollectionInfo]:
            with self._lock:
                client = self._connect()
                out: list[CollectionInfo] = []
                for cname, config in client.collections.list_all().items():
                    coll = client.collections.get(cname)
                    count = coll.aggregate.over_all(total_count=True).total_count or 0
                    dim, metric = _parse_desc(getattr(config, "description", None))
                    out.append(
                        CollectionInfo(name=_from_cname(cname), dim=dim, metric=metric, count=count)
                    )
                return out

        return await asyncio.to_thread(_list)

    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None:
        import asyncio

        def _ensure() -> None:
            import weaviate.classes.config as wc

            cname = _cname(name)
            with self._lock:
                client = self._connect()
                if client.collections.exists(cname):
                    config = client.collections.get(cname).config.get()
                    existing, _ = _parse_desc(getattr(config, "description", None))
                    if existing and existing != dim:
                        raise DimensionMismatch("weaviate", existing, dim)
                    return
                distances = {
                    "cosine": wc.VectorDistances.COSINE,
                    "l2": wc.VectorDistances.L2_SQUARED,
                    "ip": wc.VectorDistances.DOT,
                }
                client.collections.create(
                    cname,
                    description=f"lga:dim={dim};metric={metric}",
                    vectorizer_config=wc.Configure.Vectorizer.none(),
                    vector_index_config=wc.Configure.VectorIndex.hnsw(
                        distance_metric=distances[metric]
                    ),
                    properties=[wc.Property(name="page_content", data_type=wc.DataType.TEXT)],
                )

        await asyncio.to_thread(_ensure)

    def _collection(self, client: weaviate.WeaviateClient, name: str) -> Any:
        cname = _cname(name)
        if not client.collections.exists(cname):
            raise CollectionMissing("weaviate", name)
        return client.collections.get(cname)

    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult:
        import asyncio

        def _upsert() -> list[str]:
            with self._lock:
                client = self._connect()
                coll = self._collection(client, collection)
                ids: list[str] = []
                with coll.batch.dynamic() as batch:
                    for doc, emb in zip(docs, embeddings, strict=True):
                        raw_id = doc.metadata.get("id")
                        oid = (
                            coerce_uuid_id(str(raw_id))
                            if raw_id
                            else content_hash_uuid(doc.page_content)
                        )
                        ids.append(oid)
                        batch.add_object(
                            properties={"page_content": doc.page_content, **doc.metadata},
                            vector=emb,
                            uuid=oid,
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
        import asyncio

        if raw_filter:
            raise VectorStoreError(
                self.backend,
                "raw_filter is not supported by the weaviate backend "
                "(v4 filters are not dict-shaped) — use the portable `filter`",
            )

        def _query() -> list[Document]:
            with self._lock:
                client = self._connect()
                coll = self._collection(client, collection)
                if filter_matches_nothing(filter):  # weaviate rejects empty contains_any
                    return []
                _, metric = _parse_desc(getattr(coll.config.get(), "description", None))
                res = coll.query.near_vector(
                    near_vector=embedding,
                    limit=k,
                    filters=_translate_filter(filter),
                    return_metadata=["distance"],
                )
                out: list[Document] = []
                for obj in res.objects:
                    props = dict(obj.properties)
                    content = str(props.pop("page_content", ""))
                    dist = getattr(obj.metadata, "distance", None)
                    score = _to_score(metric, float(dist)) if dist is not None else None
                    if score_threshold is not None and (score or 0) < score_threshold:
                        continue
                    out.append(Document(page_content=content, metadata=props, score=score))
                return out

        return await asyncio.to_thread(_query)

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int:
        import asyncio

        def _delete() -> int:
            from weaviate.classes.query import Filter

            with self._lock:
                client = self._connect()
                coll = self._collection(client, collection)
                if ids:
                    mapped = [coerce_uuid_id(i) for i in ids]
                    res = coll.data.delete_many(where=Filter.by_id().contains_any(mapped))
                    return int(res.successful)
                if filter:
                    if filter_matches_nothing(filter):  # empty $in removes nothing
                        return 0
                    where = _translate_filter(filter)
                    if where is not None:  # degenerate filters match everything
                        res = coll.data.delete_many(where=where)
                        return int(res.successful)
                # delete-all: weaviate has no match-all filter — sweep by id
                deleted = 0
                uuids = [str(obj.uuid) for obj in coll.iterator(return_properties=[])]
                for i in range(0, len(uuids), _DELETE_CHUNK):
                    chunk = uuids[i : i + _DELETE_CHUNK]
                    res = coll.data.delete_many(where=Filter.by_id().contains_any(chunk))
                    deleted += int(res.successful)
                return deleted

        return await asyncio.to_thread(_delete)
