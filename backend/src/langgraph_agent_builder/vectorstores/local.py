"""Local vector store backend (SPEC §8b.2) — zero-config, no server.

Backed by a per-connection SQLite file under ``LGA_HOME/vectors/<name>.db``
(``aiosqlite``, already a core dependency). Search is *exact* (brute-force
cosine/l2/ip over stored vectors): deterministic, dependency-light, and correct
on every platform and both storage tiers — the right trade-off for the local
tier, whose collections are small. sqlite-vec ships as a core wheel for ANN
acceleration; exact search keeps results reproducible for tests and examples.

Contract notes (see ``base.py``): the provider owns one lazily-opened
connection (schema ensured once, ``aclose()`` to release; the next call
reopens). Portable filters compile to a SQL ``WHERE`` over the metadata JSON
(``json_extract``); constructs SQLite cannot address (quoted keys, non-scalar
operands) fall back to the exact Python reference filter — never lossy either
way, because scoring is brute-force over the (pre-)filtered rows. ``local``
has no vendor filter dialect, so ``raw_filter`` is rejected with a clear error.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from pathlib import Path
from typing import Any, ClassVar, cast

import aiosqlite

from lga.sdk.ports import Document
from lga.vectorstores.base import (
    CollectionInfo,
    CollectionMissing,
    DimensionMismatch,
    Metric,
    UpsertResult,
    VectorStoreError,
    content_hash_id,
    filter_conjuncts,
    matches_filter,
)

_SAFE = re.compile(r"[^a-zA-Z0-9_]")


def _table(collection: str) -> str:
    return "c_" + _SAFE.sub("_", collection)


def _score(metric: Metric, a: list[float], b: list[float]) -> float:
    if metric == "l2":
        dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=False)))
        return 1.0 / (1.0 + dist)
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    if metric == "ip":
        return dot
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _where(flt: dict[str, Any]) -> tuple[str, list[Any]] | None:
    """Portable filter → parameterized SQL WHERE over the metadata JSON.

    Returns ``None`` when a construct cannot be addressed in SQL (key not
    embeddable in a JSON path, non-scalar operand) — the caller then falls back
    to the exact Python filter. Unsupported operators raise (shared semantics).
    """
    scalar = (str, int, float, bool, type(None))
    clauses: list[str] = []
    params: list[Any] = []
    for key, op, operand in filter_conjuncts(flt):
        if '"' in key or "\\" in key:
            return None
        path = f'$."{key}"'
        if op == "eq":
            if not isinstance(operand, scalar):
                return None
            # IS, not =: NULL-safe, so {"key": None} matches missing keys and
            # stored JSON nulls — same as the Python reference semantics.
            clauses.append("json_extract(metadata, ?) IS ?")
            params.extend([path, operand])
        else:
            if not all(isinstance(v, scalar) for v in operand):
                return None
            values = [v for v in operand if v is not None]
            sub: list[str] = []
            if values:
                marks = ", ".join("?" for _ in values)
                sub.append(f"json_extract(metadata, ?) IN ({marks})")
                params.extend([path, *values])
            if None in operand:
                sub.append("json_extract(metadata, ?) IS NULL")
                params.append(path)
            clauses.append("(" + " OR ".join(sub) + ")" if sub else "0")
    return (" AND ".join(clauses) or "1", params)


class LocalVectorStore:
    backend: ClassVar[str] = "local"

    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        root.mkdir(parents=True, exist_ok=True)
        self._path = root / f"{_SAFE.sub('_', name)}.db"
        self._db: aiosqlite.Connection | None = None
        # one shared connection: the lock keeps multi-statement transactions
        # (upsert/delete loops + commit) from interleaving across tasks
        self._lock = asyncio.Lock()

    async def _connect(self) -> aiosqlite.Connection:
        if self._db is None:
            db = await aiosqlite.connect(self._path)
            await db.execute(
                "CREATE TABLE IF NOT EXISTS _collections "
                "(name TEXT PRIMARY KEY, dim INTEGER, metric TEXT)"
            )
            await db.commit()
            self._db = db
        return self._db

    async def aclose(self) -> None:
        """Release the connection; a later call lazily reopens."""
        async with self._lock:
            if self._db is not None:
                db, self._db = self._db, None
                await db.close()

    async def health(self) -> None:
        try:
            async with self._lock:
                db = await self._connect()
                await db.execute("SELECT 1")
        except Exception as exc:  # pragma: no cover - fs errors
            raise VectorStoreError(self.backend, str(exc)) from exc

    async def list_collections(self) -> list[CollectionInfo]:
        async with self._lock:
            db = await self._connect()
            out: list[CollectionInfo] = []
            async with db.execute("SELECT name, dim, metric FROM _collections") as cur:
                rows = await cur.fetchall()
            for name, dim, metric in rows:
                async with db.execute(f"SELECT COUNT(*) FROM {_table(name)}") as c2:
                    (count,) = cast("tuple[int]", await c2.fetchone())
                out.append(CollectionInfo(name=name, dim=dim, metric=metric, count=count))
            return out

    async def _collection_meta(
        self, db: aiosqlite.Connection, name: str
    ) -> tuple[int, Metric] | None:
        async with db.execute(
            "SELECT dim, metric FROM _collections WHERE name = ?", (name,)
        ) as cur:
            row = await cur.fetchone()
        return (row[0], row[1]) if row else None

    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None:
        async with self._lock:
            db = await self._connect()
            existing = await self._collection_meta(db, name)
            if existing is not None:
                if existing[0] != dim:
                    raise DimensionMismatch(self.backend, existing[0], dim)
                return
            await db.execute(
                "INSERT INTO _collections (name, dim, metric) VALUES (?, ?, ?)",
                (name, dim, metric),
            )
            await db.execute(
                f"CREATE TABLE IF NOT EXISTS {_table(name)} "
                "(id TEXT PRIMARY KEY, content TEXT, metadata TEXT, embedding TEXT)"
            )
            await db.commit()

    async def upsert(
        self, collection: str, docs: list[Document], embeddings: list[list[float]]
    ) -> UpsertResult:
        if len(docs) != len(embeddings):
            raise VectorStoreError(self.backend, "docs/embeddings length mismatch")
        async with self._lock:
            db = await self._connect()
            meta = await self._collection_meta(db, collection)
            if meta is None:
                raise CollectionMissing(self.backend, collection)
            dim = meta[0]
            ids: list[str] = []
            for doc, emb in zip(docs, embeddings, strict=True):
                if len(emb) != dim:
                    raise DimensionMismatch(self.backend, dim, len(emb))
                doc_id = str(doc.metadata.get("id") or content_hash_id(doc.page_content))
                ids.append(doc_id)
                await db.execute(
                    f"INSERT OR REPLACE INTO {_table(collection)} "
                    "(id, content, metadata, embedding) VALUES (?, ?, ?, ?)",
                    (doc_id, doc.page_content, json.dumps(doc.metadata), json.dumps(emb)),
                )
            await db.commit()
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
                "raw_filter is not supported by the local backend — use the portable `filter`",
            )
        translated = _where(filter) if filter else ("1", [])
        async with self._lock:
            db = await self._connect()
            meta = await self._collection_meta(db, collection)
            if meta is None:
                raise CollectionMissing(self.backend, collection)
            dim, metric = meta
            if len(embedding) != dim:
                raise DimensionMismatch(self.backend, dim, len(embedding))
            sql = f"SELECT content, metadata, embedding FROM {_table(collection)}"
            params: list[Any] = []
            if translated is not None:
                clause, params = translated
                sql += f" WHERE {clause}"
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()

        scored: list[Document] = []
        for content, metadata_json, emb_json in rows:
            metadata = json.loads(metadata_json)
            if translated is None and not matches_filter(metadata, filter):
                continue
            score = _score(metric, embedding, json.loads(emb_json))
            if score_threshold is not None and score < score_threshold:
                continue
            scored.append(Document(page_content=content, metadata=metadata, score=score))
        scored.sort(key=lambda d: d.score or 0.0, reverse=True)
        return scored[:k]

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
    ) -> int:
        async with self._lock:
            db = await self._connect()
            meta = await self._collection_meta(db, collection)
            if meta is None:
                raise CollectionMissing(self.backend, collection)
            deleted = 0
            if ids:
                for doc_id in ids:
                    cur = await db.execute(
                        f"DELETE FROM {_table(collection)} WHERE id = ?", (doc_id,)
                    )
                    deleted += cur.rowcount
            elif filter:
                translated = _where(filter)
                if translated is not None:
                    clause, params = translated
                    cur = await db.execute(
                        f"DELETE FROM {_table(collection)} WHERE {clause}", params
                    )
                    deleted = cur.rowcount
                else:
                    async with db.execute(f"SELECT id, metadata FROM {_table(collection)}") as cur2:
                        rows = await cur2.fetchall()
                    victims = [rid for rid, mj in rows if matches_filter(json.loads(mj), filter)]
                    for rid in victims:
                        await db.execute(f"DELETE FROM {_table(collection)} WHERE id = ?", (rid,))
                    deleted = len(victims)
            else:
                cur = await db.execute(f"DELETE FROM {_table(collection)}")
                deleted = cur.rowcount
            await db.commit()
            return deleted
