"""Contract suite: every built-in backend must honour the one shared
``VectorStoreProvider`` contract (SPEC §8b.1) documented in
``lab/vectorstores/base.py`` — deterministic ids, native filter translation
applied *before* top-k, normalized scores per metric, and uniform delete
semantics.

Backends run when their client extra is importable (and, for server-backed
ones, when the server is reachable):

* ``local`` — always (core).
* ``qdrant`` — in-process local mode (``path=``), when ``qdrant-client`` is installed.
* ``chroma`` — embedded ``PersistentClient``, when ``chromadb`` is installed.
* ``pgvector`` — docker-compose Postgres on :55432 (throwaway database per test).
* ``weaviate`` — needs a live server: opt-in via ``LAB_TEST_WEAVIATE_URL`` +
  the ``integration`` marker. Further live-server smoke tests live in
  ``tests/integration/test_vectorstore_live.py``.
"""

from __future__ import annotations

import importlib.util
import math
import os
import socket
import uuid
from typing import TYPE_CHECKING

import pytest

from langgraph_agent_builder.sdk.ports import Document
from langgraph_agent_builder.vectorstores import build_provider
from langgraph_agent_builder.vectorstores.base import (
    CollectionInfo,
    CollectionMissing,
    DimensionMismatch,
    VectorStoreError,
    VectorStoreProvider,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

DIM = 8
PG_ADMIN_DSN = "postgres://lab:lab@localhost:55432/lab"
WEAVIATE_URL = os.environ.get("LAB_TEST_WEAVIATE_URL")


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _pg_up() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("localhost", 55432)) == 0


PG_AVAILABLE = _installed("asyncpg") and _pg_up()

BACKENDS = [
    pytest.param("local", id="local"),
    pytest.param(
        "qdrant",
        marks=pytest.mark.skipif(
            not _installed("qdrant_client"), reason="qdrant extra not installed"
        ),
        id="qdrant",
    ),
    pytest.param(
        "chroma",
        marks=pytest.mark.skipif(not _installed("chromadb"), reason="chroma extra not installed"),
        id="chroma",
    ),
    pytest.param(
        "pgvector",
        marks=pytest.mark.skipif(not PG_AVAILABLE, reason="postgres :55432 not reachable"),
        id="pgvector",
    ),
    pytest.param(
        "weaviate",
        marks=[
            pytest.mark.integration,
            pytest.mark.skipif(
                not (WEAVIATE_URL and _installed("weaviate")),
                reason="set LAB_TEST_WEAVIATE_URL (and install the weaviate extra)",
            ),
        ],
        id="weaviate",
    ),
]


async def _fresh_pg_dsn() -> str:
    import asyncpg  # type: ignore[import-untyped]  # asyncpg ships no py.typed marker

    name = f"lga_vec_test_{uuid.uuid4().hex[:10]}"
    conn = await asyncpg.connect(PG_ADMIN_DSN)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
    return f"postgres://lab:lab@localhost:55432/{name}"


@pytest.fixture(params=BACKENDS)
async def provider(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[VectorStoreProvider]:
    backend: str = request.param
    if backend == "local":
        built = build_provider("local", "contract", home=tmp_path)
    elif backend == "qdrant":
        built = build_provider("qdrant", "contract", {"path": str(tmp_path / "qdrant")})
    elif backend == "chroma":
        built = build_provider("chroma", "contract", {"path": str(tmp_path / "chroma")})
    elif backend == "pgvector":
        built = build_provider("pgvector", "contract", {"dsn": await _fresh_pg_dsn()})
    else:
        built = build_provider("weaviate", "contract", {"url": WEAVIATE_URL})
    yield built
    closer = getattr(built, "aclose", None)
    if closer is not None:
        await closer()


def _vec(x: float, y: float = 0.0) -> list[float]:
    return [x, y] + [0.0] * (DIM - 2)


def _unit(sim: float) -> list[float]:
    """Unit vector whose cosine similarity to ``_vec(1.0)`` is exactly ``sim``."""
    return _vec(sim, math.sqrt(max(0.0, 1.0 - sim * sim)))


QUERY = _vec(1.0)


async def _seed(
    provider: VectorStoreProvider,
    collection: str,
    rows: list[tuple[float, dict[str, object]]],
) -> None:
    """Upsert one doc per (cosine-sim, metadata) with contract-exact vectors."""
    await provider.ensure_collection(collection, DIM, metric="cosine")
    docs = [
        Document(page_content=f"doc-{i}", metadata=dict(meta)) for i, (_, meta) in enumerate(rows)
    ]
    await provider.upsert(collection, docs, [_unit(sim) for sim, _ in rows])


# --------------------------------------------------------------------------- protocol shape
async def test_satisfies_provider_protocol(provider: VectorStoreProvider) -> None:
    # runtime_checkable structural conformance (SPEC §8b.1)
    assert isinstance(provider, VectorStoreProvider)
    assert provider.backend in {"local", "pgvector", "qdrant", "weaviate", "chroma"}


# --------------------------------------------------------------------------- round trip
async def test_round_trip(provider: VectorStoreProvider) -> None:
    await provider.health()
    await provider.ensure_collection("kb", DIM, metric="cosine")
    listed = await provider.list_collections()
    (info,) = [c for c in listed if c.name == "kb"]
    assert isinstance(info, CollectionInfo)
    assert info.dim == DIM

    docs = [Document(page_content="alpha"), Document(page_content="beta")]
    result = await provider.upsert("kb", docs, [_unit(1.0), _unit(0.0)])
    assert result.count == 2
    assert len(set(result.ids)) == 2

    hits = await provider.query("kb", QUERY, k=1)
    assert len(hits) == 1
    assert hits[0].page_content == "alpha"
    assert hits[0].score == pytest.approx(1.0, abs=1e-3)

    (info,) = [c for c in await provider.list_collections() if c.name == "kb"]
    assert info.count == 2


async def test_ensure_collection_idempotent_and_dim_pinned(
    provider: VectorStoreProvider,
) -> None:
    await provider.ensure_collection("kb", DIM)
    await provider.ensure_collection("kb", DIM)  # same dim → no-op
    with pytest.raises(DimensionMismatch):
        await provider.ensure_collection("kb", DIM + 1)


async def test_query_missing_collection_raises(provider: VectorStoreProvider) -> None:
    with pytest.raises(CollectionMissing):
        await provider.query("ghost", QUERY)


async def test_delete_missing_collection_raises(provider: VectorStoreProvider) -> None:
    with pytest.raises(CollectionMissing):
        await provider.delete("ghost")


# --------------------------------------------------------------------------- deterministic ids
async def test_reingest_upserts_instead_of_duplicating(provider: VectorStoreProvider) -> None:
    """Content-hash default ids (base.py contract): re-ingesting the same docs
    must not grow the collection, and must yield the same ids."""
    await provider.ensure_collection("kb", DIM)
    docs = [Document(page_content="alpha"), Document(page_content="beta")]
    embs = [_unit(1.0), _unit(0.5)]
    first = await provider.upsert("kb", docs, embs)
    second = await provider.upsert("kb", list(docs), embs)
    assert first.ids == second.ids
    (info,) = [c for c in await provider.list_collections() if c.name == "kb"]
    assert info.count == 2


# --------------------------------------------------------------------------- filters
async def test_filter_returns_matches_beyond_unfiltered_topk(
    provider: VectorStoreProvider,
) -> None:
    """The regression the contract exists for: matching docs must surface even
    when none of them are in the *unfiltered* top-k (filter before top-k)."""
    rows: list[tuple[float, dict[str, object]]] = [
        (0.99, {"tenant": "other"}),
        (0.98, {"tenant": "other"}),
        (0.97, {"tenant": "other"}),
        (0.96, {"tenant": "other"}),
        (0.30, {"tenant": "acme"}),
        (0.20, {"tenant": "acme"}),
    ]
    await _seed(provider, "kb", rows)
    hits = await provider.query("kb", QUERY, k=2, filter={"tenant": "acme"})
    assert len(hits) == 2
    assert all(h.metadata["tenant"] == "acme" for h in hits)


async def test_filter_in_and_and(provider: VectorStoreProvider) -> None:
    rows: list[tuple[float, dict[str, object]]] = [
        (0.9, {"lang": "en", "n": 1}),
        (0.8, {"lang": "en", "n": 9}),
        (0.7, {"lang": "de", "n": 1}),
    ]
    await _seed(provider, "kb", rows)
    flt = {"$and": [{"lang": "en"}, {"n": {"$in": [1, 2]}}]}
    hits = await provider.query("kb", QUERY, k=3, filter=flt)
    assert len(hits) == 1
    assert hits[0].metadata["lang"] == "en"


async def test_filter_empty_in_matches_nothing(provider: VectorStoreProvider) -> None:
    """An empty ``$in`` can never match (base.py contract) — it must neither
    error on vendor APIs nor degrade to match-all (qdrant delete would
    otherwise wipe the collection)."""
    await _seed(provider, "kb", [(0.9, {"n": 1})])
    assert await provider.query("kb", QUERY, k=5, filter={"n": {"$in": []}}) == []
    assert await provider.delete("kb", filter={"n": {"$in": []}}) == 0
    (info,) = [c for c in await provider.list_collections() if c.name == "kb"]
    assert info.count == 1


async def test_unsupported_filter_operator_raises(provider: VectorStoreProvider) -> None:
    await _seed(provider, "kb", [(0.9, {"n": 5})])
    with pytest.raises(VectorStoreError, match=r"\$gt"):
        await provider.query("kb", QUERY, k=1, filter={"n": {"$gt": 3}})


async def test_filter_and_raw_filter_are_exclusive_or_rejected(
    provider: VectorStoreProvider,
) -> None:
    """Backends either reject raw_filter outright (local/pgvector/weaviate) or
    reject the *combination* with a portable filter — never silently merge."""
    await _seed(provider, "kb", [(0.9, {"lang": "en"})])
    with pytest.raises(VectorStoreError):
        await provider.query(
            "kb", QUERY, k=1, filter={"lang": "en"}, raw_filter={"lang": {"$eq": "en"}}
        )


# --------------------------------------------------------------------------- scores
async def test_cosine_scores_are_similarities(provider: VectorStoreProvider) -> None:
    await _seed(provider, "kb", [(1.0, {"which": "same"}), (0.0, {"which": "orthogonal"})])
    hits = await provider.query("kb", QUERY, k=2)
    by_meta = {h.metadata["which"]: h.score for h in hits}
    assert by_meta["same"] == pytest.approx(1.0, abs=1e-3)
    assert by_meta["orthogonal"] == pytest.approx(0.0, abs=1e-3)


async def test_score_threshold_uses_normalized_scores(provider: VectorStoreProvider) -> None:
    await _seed(provider, "kb", [(1.0, {"i": 0}), (0.2, {"i": 1})])
    hits = await provider.query("kb", QUERY, k=2, score_threshold=0.9)
    assert [h.metadata["i"] for h in hits] == [0]


async def test_l2_scores_follow_contract(provider: VectorStoreProvider) -> None:
    """l2 score = 1/(1+d) with d the euclidean distance (base.py contract)."""
    await provider.ensure_collection("l2kb", DIM, metric="l2")
    docs = [Document(page_content="near"), Document(page_content="far")]
    await provider.upsert("l2kb", docs, [_vec(0.0), _vec(3.0)])
    hits = await provider.query("l2kb", _vec(0.0), k=2)
    by_content = {h.page_content: h.score for h in hits}
    assert by_content["near"] == pytest.approx(1.0, abs=1e-3)
    assert by_content["far"] == pytest.approx(1.0 / 4.0, abs=1e-3)


async def test_ip_scores_are_raw_dot_products(provider: VectorStoreProvider) -> None:
    await provider.ensure_collection("ipkb", DIM, metric="ip")
    docs = [Document(page_content="big"), Document(page_content="small")]
    await provider.upsert("ipkb", docs, [_vec(3.0), _vec(1.0)])
    hits = await provider.query("ipkb", _vec(2.0), k=2)
    by_content = {h.page_content: h.score for h in hits}
    assert by_content["big"] == pytest.approx(6.0, abs=1e-3)
    assert by_content["small"] == pytest.approx(2.0, abs=1e-3)


# --------------------------------------------------------------------------- delete
async def test_delete_by_ids_returns_exact_count(provider: VectorStoreProvider) -> None:
    await provider.ensure_collection("kb", DIM)
    docs = [Document(page_content="a"), Document(page_content="b")]
    result = await provider.upsert("kb", docs, [_unit(1.0), _unit(0.5)])
    assert await provider.delete("kb", ids=[result.ids[0]]) == 1
    assert await provider.delete("kb", ids=["definitely-not-there"]) == 0
    (info,) = [c for c in await provider.list_collections() if c.name == "kb"]
    assert info.count == 1


async def test_delete_by_filter(provider: VectorStoreProvider) -> None:
    rows: list[tuple[float, dict[str, object]]] = [
        (0.9, {"lang": "en"}),
        (0.8, {"lang": "de"}),
        (0.7, {"lang": "en"}),
    ]
    await _seed(provider, "kb", rows)
    assert await provider.delete("kb", filter={"lang": "en"}) == 2
    hits = await provider.query("kb", QUERY, k=1)
    assert [h.metadata["lang"] for h in hits] == ["de"]


async def test_delete_all_when_no_ids_or_filter(provider: VectorStoreProvider) -> None:
    await _seed(provider, "kb", [(0.9, {"i": 0}), (0.8, {"i": 1}), (0.7, {"i": 2})])
    assert await provider.delete("kb") == 3
    (info,) = [c for c in await provider.list_collections() if c.name == "kb"]
    assert info.count == 0


# --------------------------------------------------------------------------- registry
def test_build_provider_unknown_backend_raises(tmp_path: Path) -> None:
    with pytest.raises(VectorStoreError, match="unknown vector store backend"):
        build_provider("nope", "x", home=tmp_path)
