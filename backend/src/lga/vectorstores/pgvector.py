"""pgvector backend (SPEC §8b.2) — extra ``lga[pgvector]``, table-per-collection.

Uses ``asyncpg`` + the ``vector`` extension directly (no LangChain wrapper) so
the abstraction owns the schema. Can reuse the app DB when the storage tier is
Postgres (``dsn`` omitted → falls back to ``LGA_DATABASE_URL``).
"""

from __future__ import annotations

import json
import re
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
    import asyncpg  # type: ignore[import-untyped]  # asyncpg ships no py.typed marker

_SAFE = re.compile(r"[^a-zA-Z0-9_]")
_OPS = {"cosine": "<=>", "l2": "<->", "ip": "<#>"}


def _table(collection: str) -> str:
    return "lga_vec_" + _SAFE.sub("_", collection)


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

    async def _conn(self) -> asyncpg.Connection:
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - needs extra
            raise BackendExtraMissing("pgvector", "pgvector") from exc
        try:
            conn = await asyncpg.connect(self._dsn)
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS lga_vec_collections "
                "(name TEXT PRIMARY KEY, dim INT, metric TEXT)"
            )
            return conn
        except BackendExtraMissing:
            raise
        except Exception as exc:
            raise VectorStoreError(self.backend, str(exc)) from exc

    async def health(self) -> None:
        conn = await self._conn()
        await conn.close()

    async def list_collections(self) -> list[CollectionInfo]:
        conn = await self._conn()
        try:
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
        finally:
            await conn.close()

    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None:
        conn = await self._conn()
        try:
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
        finally:
            await conn.close()

    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult:
        import uuid

        conn = await self._conn()
        try:
            ids: list[str] = []
            for doc, emb in zip(docs, embeddings, strict=True):
                doc_id = str(doc.metadata.get("id") or uuid.uuid4())
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
        finally:
            await conn.close()

    async def query(
        self,
        collection: str,
        embedding: list[float],
        k: int = 4,
        filter: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[Document]:
        conn = await self._conn()
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM lga_vec_collections WHERE name = $1", collection
            )
            if not exists:
                raise CollectionMissing(self.backend, collection)
            metric = await conn.fetchval(
                "SELECT metric FROM lga_vec_collections WHERE name = $1", collection
            )
            op = _OPS.get(metric, "<=>")
            rows = await conn.fetch(
                f"SELECT content, metadata, 1 - (embedding {op} $1) AS score "
                f"FROM {_table(collection)} ORDER BY embedding {op} $1 LIMIT $2",
                str(embedding),
                max(k * 4, k),
            )
            out: list[Document] = []
            for r in rows:
                metadata = (
                    json.loads(r["metadata"])
                    if isinstance(r["metadata"], str)
                    else dict(r["metadata"] or {})
                )
                if not matches_filter(metadata, filter):
                    continue
                score = float(r["score"])
                if score_threshold is not None and score < score_threshold:
                    continue
                out.append(Document(page_content=r["content"], metadata=metadata, score=score))
                if len(out) >= k:
                    break
            return out
        finally:
            await conn.close()

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int:
        conn = await self._conn()
        try:
            if ids:
                result = await conn.execute(
                    f"DELETE FROM {_table(collection)} WHERE id = ANY($1)", ids
                )
                return int(result.split()[-1])
            if filter is None:
                result = await conn.execute(f"DELETE FROM {_table(collection)}")
                return int(result.split()[-1])
            rows = await conn.fetch(f"SELECT id, metadata FROM {_table(collection)}")
            victims = [
                r["id"]
                for r in rows
                if matches_filter(
                    json.loads(r["metadata"])
                    if isinstance(r["metadata"], str)
                    else dict(r["metadata"] or {}),
                    filter,
                )
            ]
            if victims:
                await conn.execute(f"DELETE FROM {_table(collection)} WHERE id = ANY($1)", victims)
            return len(victims)
        finally:
            await conn.close()
