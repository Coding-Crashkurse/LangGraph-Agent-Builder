"""pgvector backend (SPEC §8b.2) — extra
``langgraph-agent-builder[pgvector]``, table-per-collection.

Uses ``asyncpg`` + the ``vector`` extension directly (no LangChain wrapper) so
the abstraction owns the schema. Can reuse the app DB when the storage tier is
Postgres (``dsn`` omitted → falls back to ``LGA_DATABASE_URL``).

Contract notes (see ``base.py``): the provider owns a lazily-created asyncpg
pool; ``CREATE EXTENSION``/catalog DDL runs once per provider, not per call.
Portable filters compile to parameterized JSONB ``WHERE`` conjuncts applied
*before* ``ORDER BY … LIMIT k`` — filtered search is exact, nothing is lost to
post-filtering. Scores are exact per metric (cosine similarity, ``1/(1+d)``
for l2, raw inner product for ip) and delete counts are exact. pgvector has no
vendor filter dialect (raw SQL would be an injection hazard), so ``raw_filter``
is rejected with a clear error.
"""

from __future__ import annotations

import asyncio
import json
import re
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
    content_hash_id,
    filter_conjuncts,
)

if TYPE_CHECKING:
    import asyncpg  # type: ignore[import-untyped]  # asyncpg ships no py.typed marker

_SAFE = re.compile(r"[^a-zA-Z0-9_]")
_OPS = {"cosine": "<=>", "l2": "<->", "ip": "<#>"}
# exact normalized score per metric (base.py contract); <#> is the *negative*
# inner product, hence the sign flip
_SCORE = {
    "cosine": "1 - (embedding <=> $1)",
    "l2": "1 / (1 + (embedding <-> $1))",
    "ip": "-(embedding <#> $1)",
}
_INDEX_OPS = {"cosine": "vector_cosine_ops", "l2": "vector_l2_ops", "ip": "vector_ip_ops"}


def _table(collection: str) -> str:
    return "lga_vec_" + _SAFE.sub("_", collection)


def _where_sql(flt: dict[str, Any] | None, start: int) -> tuple[str, list[Any]]:
    """Portable filter → parameterized JSONB WHERE conjuncts (``$start``-based).

    ``None`` equality matches missing keys *and* stored JSON nulls — same as
    the Python reference semantics in :func:`lga.vectorstores.base.matches_filter`.
    """
    clauses: list[str] = []
    params: list[Any] = []
    n = start
    for key, op, operand in filter_conjuncts(flt):
        field = f"metadata->(${n}::text)"
        params.append(key)
        n += 1
        if op == "eq":
            if operand is None:
                clauses.append(f"({field} IS NULL OR {field} = 'null'::jsonb)")
                continue
            clauses.append(f"{field} = ${n}::jsonb")
            params.append(json.dumps(operand))
            n += 1
        else:
            values = [json.dumps(v) for v in operand if v is not None]
            sub = [f"{field} = ANY(${n}::jsonb[])"]
            params.append(values)
            n += 1
            if None in operand:
                sub.append(f"{field} IS NULL OR {field} = 'null'::jsonb")
            clauses.append("(" + " OR ".join(sub) + ")")
    return (" AND ".join(clauses), params)


class PgVectorStore:
    backend: ClassVar[str] = "pgvector"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        dsn = params.get("dsn") or params.get("app_database")
        if not dsn:
            from lga.services.settings import get_settings

            dsn = str(get_settings().database_url)
        self._dsn = re.sub(r"\+\w+", "", str(dsn)).replace("postgresql://", "postgres://")
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def _get_pool(self) -> asyncpg.Pool:
        """Lazily create the pool and run the one-time schema DDL."""
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - needs extra
            raise BackendExtraMissing("pgvector", "pgvector") from exc
        async with self._lock:
            if self._pool is None:
                try:
                    pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
                    async with pool.acquire() as conn:
                        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                        await conn.execute(
                            "CREATE TABLE IF NOT EXISTS lga_vec_collections "
                            "(name TEXT PRIMARY KEY, dim INT, metric TEXT)"
                        )
                    self._pool = pool
                except Exception as exc:
                    raise VectorStoreError(self.backend, str(exc)) from exc
            return self._pool

    async def aclose(self) -> None:
        """Release the pool; a later call lazily reconnects."""
        async with self._lock:
            if self._pool is not None:
                pool, self._pool = self._pool, None
                await pool.close()

    async def _meta(self, conn: asyncpg.Connection, collection: str) -> tuple[int, str]:
        row = await conn.fetchrow(
            "SELECT dim, metric FROM lga_vec_collections WHERE name = $1", collection
        )
        if row is None:
            raise CollectionMissing(self.backend, collection)
        return int(row["dim"]), str(row["metric"])

    async def health(self) -> None:
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
        except Exception as exc:
            raise VectorStoreError(self.backend, str(exc)) from exc

    async def list_collections(self) -> list[CollectionInfo]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT name, dim, metric FROM lga_vec_collections")
            out: list[CollectionInfo] = []
            for r in rows:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {_table(r['name'])}")
                out.append(
                    CollectionInfo(
                        name=r["name"], dim=r["dim"], metric=r["metric"], count=count or 0
                    )
                )
            return out

    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT dim FROM lga_vec_collections WHERE name = $1", name)
            if row is not None:
                if int(row["dim"]) != dim:
                    raise DimensionMismatch(self.backend, int(row["dim"]), dim)
                return
            await conn.execute(
                "INSERT INTO lga_vec_collections (name, dim, metric) VALUES ($1, $2, $3) "
                "ON CONFLICT (name) DO NOTHING",
                name,
                dim,
                metric,
            )
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_table(name)} "
                f"(id TEXT PRIMARY KEY, content TEXT, metadata JSONB, embedding vector({dim}))"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS {_table(name)}_hnsw ON {_table(name)} "
                f"USING hnsw (embedding {_INDEX_OPS.get(metric, 'vector_cosine_ops')})"
            )

    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult:
        if len(docs) != len(embeddings):
            raise VectorStoreError(self.backend, "docs/embeddings length mismatch")
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            dim, _ = await self._meta(conn, collection)
            ids: list[str] = []
            async with conn.transaction():
                for doc, emb in zip(docs, embeddings, strict=True):
                    if len(emb) != dim:
                        raise DimensionMismatch(self.backend, dim, len(emb))
                    doc_id = str(doc.metadata.get("id") or content_hash_id(doc.page_content))
                    ids.append(doc_id)
                    await conn.execute(
                        f"INSERT INTO {_table(collection)} (id, content, metadata, embedding) "
                        "VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO UPDATE "
                        "SET content = EXCLUDED.content, metadata = EXCLUDED.metadata, "
                        "embedding = EXCLUDED.embedding",
                        doc_id,
                        doc.page_content,
                        json.dumps(doc.metadata),
                        str(emb),
                    )
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
        if raw_filter:
            raise VectorStoreError(
                self.backend,
                "raw_filter is not supported by the pgvector backend — use the portable `filter`",
            )
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            dim, metric = await self._meta(conn, collection)
            if len(embedding) != dim:
                raise DimensionMismatch(self.backend, dim, len(embedding))
            where, extra = _where_sql(filter, start=3)
            sql = f"SELECT content, metadata, {_SCORE[metric]} AS score FROM {_table(collection)}"
            if where:
                sql += f" WHERE {where}"
            sql += f" ORDER BY embedding {_OPS[metric]} $1 LIMIT $2"
            rows = await conn.fetch(sql, str(embedding), k, *extra)
            out: list[Document] = []
            for r in rows:
                metadata = (
                    json.loads(r["metadata"])
                    if isinstance(r["metadata"], str)
                    else dict(r["metadata"] or {})
                )
                score = float(r["score"])
                if score_threshold is not None and score < score_threshold:
                    continue
                out.append(Document(page_content=r["content"], metadata=metadata, score=score))
            return out

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._meta(conn, collection)
            if ids:
                result = await conn.execute(
                    f"DELETE FROM {_table(collection)} WHERE id = ANY($1)", ids
                )
                return int(result.split()[-1])
            if filter:
                where, params = _where_sql(filter, start=1)
                if where:  # degenerate filters ({"$and": []}) match everything
                    result = await conn.execute(
                        f"DELETE FROM {_table(collection)} WHERE {where}", *params
                    )
                    return int(result.split()[-1])
            result = await conn.execute(f"DELETE FROM {_table(collection)}")
            return int(result.split()[-1])
