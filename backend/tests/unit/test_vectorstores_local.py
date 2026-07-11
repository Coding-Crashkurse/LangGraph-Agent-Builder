"""Unit tests for the local (sqlite-backed) vector store and the shared
``lga.vectorstores.base`` abstraction (SPEC §8b).

Covered behaviour:
* portable filter semantics (equality / ``$in`` / ``$eq`` / ``$and`` and the
  ``VectorStoreError`` raised on unsupported operators),
* the deterministic id helpers (content hash / UUID coercion) and the
  ``filter_conjuncts`` / ``check_filter_args`` translation helpers,
* the typed error hierarchy (attributes + messages),
* the exact ``_score`` metrics (cosine / l2 / ip) and table-name sanitisation,
* the full ``LocalVectorStore`` lifecycle: ensure/list/upsert/query/delete plus
  every error branch (missing collection, dimension mismatch, length mismatch),
  the ``aclose``/reopen cycle, and the SQL-filter → Python-filter fallback.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from lga.components.llm._models import resolve_embeddings
from lga.sdk.ports import Document
from lga.vectorstores.base import (
    BackendExtraMissing,
    CollectionInfo,
    CollectionMissing,
    DimensionMismatch,
    UpsertResult,
    VectorStoreError,
    check_filter_args,
    coerce_uuid_id,
    content_hash_id,
    content_hash_uuid,
    filter_conjuncts,
    filter_matches_nothing,
    matches_filter,
)
from lga.vectorstores.local import LocalVectorStore, _score, _table

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.embeddings import Embeddings

DIM = 8


@pytest.fixture
def store(tmp_path: Path) -> LocalVectorStore:
    return LocalVectorStore("my store", tmp_path / "vectors")


@pytest.fixture
def embeddings() -> Embeddings:
    return resolve_embeddings({"provider": "fake", "dim": DIM})


def _embed(emb: Embeddings, texts: list[str]) -> list[list[float]]:
    return emb.embed_documents(texts)


# --------------------------------------------------------------------------- matches_filter
def test_matches_filter_none_is_always_true() -> None:
    assert matches_filter({"a": 1}, None) is True


def test_matches_filter_empty_dict_is_always_true() -> None:
    assert matches_filter({"a": 1}, {}) is True


def test_matches_filter_scalar_equality() -> None:
    assert matches_filter({"lang": "en"}, {"lang": "en"}) is True
    assert matches_filter({"lang": "de"}, {"lang": "en"}) is False


def test_matches_filter_missing_key_fails_equality() -> None:
    assert matches_filter({"other": 1}, {"lang": "en"}) is False


def test_matches_filter_in_operator() -> None:
    assert matches_filter({"lang": "en"}, {"lang": {"$in": ["en", "de"]}}) is True
    assert matches_filter({"lang": "fr"}, {"lang": {"$in": ["en", "de"]}}) is False


def test_matches_filter_eq_operator() -> None:
    assert matches_filter({"n": 3}, {"n": {"$eq": 3}}) is True
    assert matches_filter({"n": 4}, {"n": {"$eq": 3}}) is False


def test_matches_filter_and_all_true() -> None:
    flt = {"$and": [{"lang": "en"}, {"n": {"$in": [1, 2]}}]}
    assert matches_filter({"lang": "en", "n": 2}, flt) is True


def test_matches_filter_and_one_false() -> None:
    flt = {"$and": [{"lang": "en"}, {"n": {"$in": [1, 2]}}]}
    assert matches_filter({"lang": "en", "n": 9}, flt) is False


def test_matches_filter_unsupported_top_level_operator() -> None:
    with pytest.raises(VectorStoreError) as exc:
        matches_filter({"a": 1}, {"$or": [{"a": 1}]})
    assert "$or" in str(exc.value)
    assert exc.value.backend == "filter"


def test_matches_filter_unsupported_nested_operator() -> None:
    with pytest.raises(VectorStoreError) as exc:
        matches_filter({"n": 5}, {"n": {"$gt": 3}})
    assert "$gt" in str(exc.value)


# --------------------------------------------------------------------------- id helpers
def test_content_hash_id_is_deterministic_hex() -> None:
    a = content_hash_id("alpha")
    assert a == content_hash_id("alpha")  # process-independent, unlike hash()
    assert a != content_hash_id("beta")
    assert len(a) == 24
    int(a, 16)  # hex-truncated sha256


def test_content_hash_uuid_is_a_valid_deterministic_uuid() -> None:
    u = content_hash_uuid("alpha")
    assert u == content_hash_uuid("alpha")
    assert str(uuid.UUID(u)) == u


def test_coerce_uuid_id_passes_uuids_and_maps_other_ids() -> None:
    native = str(uuid.uuid4())
    assert coerce_uuid_id(native) == native
    mapped = coerce_uuid_id("doc-1")
    assert mapped == coerce_uuid_id("doc-1")  # deterministic → upsert/delete round-trip
    assert str(uuid.UUID(mapped)) == mapped
    assert coerce_uuid_id("doc-2") != mapped


# --------------------------------------------------------------------------- filter helpers
def test_filter_conjuncts_flattens_to_key_op_operand() -> None:
    flt = {"$and": [{"lang": "en"}, {"n": {"$in": (1, 2)}}], "k": {"$eq": 3}}
    assert filter_conjuncts(flt) == [("lang", "eq", "en"), ("n", "in", [1, 2]), ("k", "eq", 3)]


def test_filter_conjuncts_empty_inputs() -> None:
    assert filter_conjuncts(None) == []
    assert filter_conjuncts({}) == []


def test_filter_conjuncts_unsupported_operator_raises() -> None:
    with pytest.raises(VectorStoreError, match=r"\$gt"):
        filter_conjuncts({"n": {"$gt": 3}})
    with pytest.raises(VectorStoreError, match=r"\$or"):
        filter_conjuncts({"$or": []})


def test_filter_matches_nothing_only_on_empty_in() -> None:
    assert filter_matches_nothing({"n": {"$in": []}}) is True
    assert filter_matches_nothing({"$and": [{"a": 1}, {"n": {"$in": []}}]}) is True
    assert filter_matches_nothing({"n": {"$in": [1]}}) is False
    assert filter_matches_nothing({"$and": []}) is False  # degenerate → matches everything
    assert filter_matches_nothing(None) is False


def test_check_filter_args_rejects_the_combination() -> None:
    check_filter_args("x", {"a": 1}, None)  # either alone is fine
    check_filter_args("x", None, {"a": 1})
    with pytest.raises(VectorStoreError, match="mutually exclusive"):
        check_filter_args("x", {"a": 1}, {"a": 1})


# --------------------------------------------------------------------------- error hierarchy
def test_dimension_mismatch_attributes() -> None:
    err = DimensionMismatch("local", expected=8, got=4)
    assert err.backend == "local"
    assert err.expected == 8
    assert err.got == 4
    assert "4" in str(err)
    assert "8" in str(err)
    assert isinstance(err, VectorStoreError)


def test_collection_missing_attributes() -> None:
    err = CollectionMissing("local", "docs")
    assert err.collection == "docs"
    assert "docs" in str(err)
    assert isinstance(err, VectorStoreError)


def test_backend_extra_missing_hint() -> None:
    err = BackendExtraMissing("qdrant", "qdrant")
    assert err.extra == "qdrant"
    assert err.backend == "qdrant"
    assert 'pip install "langgraph-agent-builder[qdrant]"' in str(err)


def test_vector_store_error_prefixes_backend() -> None:
    err = VectorStoreError("local", "boom")
    assert err.backend == "local"
    assert err.detail == "boom"
    assert str(err) == "[local] boom"


def test_collection_info_and_upsert_result_defaults() -> None:
    info = CollectionInfo(name="c", dim=3)
    assert info.metric == "cosine"
    assert info.count == 0
    result = UpsertResult(count=0)
    assert result.ids == []


# --------------------------------------------------------------------------- _score / _table
def test_score_cosine_identical_vectors_is_one() -> None:
    v = [1.0, 2.0, 3.0]
    assert _score("cosine", v, v) == pytest.approx(1.0)


def test_score_cosine_orthogonal_is_zero() -> None:
    assert _score("cosine", [1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_score_cosine_zero_vector_does_not_divide_by_zero() -> None:
    # both norms fall back to 1.0 → dot(0) / 1 == 0.0, no ZeroDivisionError
    assert _score("cosine", [0.0, 0.0], [0.0, 0.0]) == 0.0


def test_score_l2_is_inverse_distance() -> None:
    # distance between the two points is 5 → 1/(1+5)
    assert _score("l2", [0.0, 0.0], [3.0, 4.0]) == pytest.approx(1.0 / 6.0)


def test_score_l2_identical_is_one() -> None:
    assert _score("l2", [1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)


def test_score_ip_is_raw_dot_product() -> None:
    assert _score("ip", [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == pytest.approx(32.0)


def test_table_sanitises_unsafe_characters() -> None:
    assert _table("my-coll.1") == "c_my_coll_1"
    assert _table("plain") == "c_plain"


# --------------------------------------------------------------------------- lifecycle
async def test_init_creates_root_directory(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "vectors"
    LocalVectorStore("s", root)
    assert root.is_dir()


async def test_health_ok(store: LocalVectorStore) -> None:
    # a healthy backend simply returns without raising
    await store.health()


async def test_ensure_and_list_collections(store: LocalVectorStore) -> None:
    await store.ensure_collection("docs", DIM, metric="l2")
    infos = await store.list_collections()
    assert len(infos) == 1
    info = infos[0]
    assert info.name == "docs"
    assert info.dim == DIM
    assert info.metric == "l2"
    assert info.count == 0


async def test_ensure_collection_idempotent(store: LocalVectorStore) -> None:
    await store.ensure_collection("docs", DIM)
    await store.ensure_collection("docs", DIM)  # same dim → no-op, no raise
    assert len(await store.list_collections()) == 1


async def test_ensure_collection_dimension_mismatch(store: LocalVectorStore) -> None:
    await store.ensure_collection("docs", DIM)
    with pytest.raises(DimensionMismatch) as exc:
        await store.ensure_collection("docs", DIM + 1)
    assert exc.value.expected == DIM
    assert exc.value.got == DIM + 1


async def test_upsert_length_mismatch(store: LocalVectorStore) -> None:
    await store.ensure_collection("docs", DIM)
    with pytest.raises(VectorStoreError, match="length mismatch"):
        await store.upsert("docs", [Document(page_content="a")], [])


async def test_upsert_missing_collection(store: LocalVectorStore) -> None:
    with pytest.raises(CollectionMissing):
        await store.upsert("ghost", [Document(page_content="a")], [[0.0] * DIM])


async def test_upsert_embedding_dimension_mismatch(store: LocalVectorStore) -> None:
    await store.ensure_collection("docs", DIM)
    with pytest.raises(DimensionMismatch) as exc:
        await store.upsert("docs", [Document(page_content="a")], [[0.0, 1.0]])
    assert exc.value.expected == DIM
    assert exc.value.got == 2


async def test_upsert_returns_ids_and_updates_count(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM)
    texts = ["alpha", "beta", "gamma"]
    docs = [Document(page_content=t) for t in texts]
    result = await store.upsert("docs", docs, _embed(embeddings, texts))
    assert result.count == 3
    assert len(result.ids) == 3
    infos = await store.list_collections()
    assert infos[0].count == 3


async def test_upsert_uses_metadata_id(store: LocalVectorStore, embeddings: Embeddings) -> None:
    await store.ensure_collection("docs", DIM)
    docs = [Document(page_content="hi", metadata={"id": "fixed-1"})]
    result = await store.upsert("docs", docs, _embed(embeddings, ["hi"]))
    assert result.ids == ["fixed-1"]


async def test_upsert_default_ids_are_content_hashes(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM)
    result = await store.upsert(
        "docs", [Document(page_content="alpha")], _embed(embeddings, ["alpha"])
    )
    assert result.ids == [content_hash_id("alpha")]
    # re-ingesting the same content (e.g. a periodic re-seed from a fresh
    # process) yields the same id → upsert, not a duplicate row
    await store.upsert("docs", [Document(page_content="alpha")], _embed(embeddings, ["alpha"]))
    assert (await store.list_collections())[0].count == 1


async def test_aclose_releases_connection_and_reopens_lazily(store: LocalVectorStore) -> None:
    await store.ensure_collection("docs", DIM)
    await store.aclose()
    assert store._db is None
    assert len(await store.list_collections()) == 1  # next call reopens


async def test_upsert_replace_same_id_does_not_duplicate(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM)
    docs = [Document(page_content="v1", metadata={"id": "x"})]
    await store.upsert("docs", docs, _embed(embeddings, ["v1"]))
    docs2 = [Document(page_content="v2", metadata={"id": "x"})]
    await store.upsert("docs", docs2, _embed(embeddings, ["v2"]))
    infos = await store.list_collections()
    assert infos[0].count == 1  # INSERT OR REPLACE, same primary key


# --------------------------------------------------------------------------- query
async def test_query_missing_collection(store: LocalVectorStore) -> None:
    with pytest.raises(CollectionMissing):
        await store.query("ghost", [0.0] * DIM)


async def test_query_embedding_dimension_mismatch(store: LocalVectorStore) -> None:
    await store.ensure_collection("docs", DIM)
    with pytest.raises(DimensionMismatch):
        await store.query("docs", [0.0, 1.0])


async def test_query_orders_by_score_descending(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM, metric="cosine")
    texts = ["the cat sat on the mat", "quantum chromodynamics", "banana bread recipe"]
    docs = [Document(page_content=t) for t in texts]
    await store.upsert("docs", docs, _embed(embeddings, texts))
    # querying with an exact stored text ⇒ that doc scores ~1.0 and ranks first
    query_vec = embeddings.embed_query(texts[0])
    results = await store.query("docs", query_vec, k=3)
    assert results[0].page_content == texts[0]
    assert results[0].score == pytest.approx(1.0)
    scores = [r.score or 0.0 for r in results]
    assert scores == sorted(scores, reverse=True)


async def test_query_respects_k_limit(store: LocalVectorStore, embeddings: Embeddings) -> None:
    await store.ensure_collection("docs", DIM)
    texts = [f"doc number {i}" for i in range(5)]
    docs = [Document(page_content=t) for t in texts]
    await store.upsert("docs", docs, _embed(embeddings, texts))
    results = await store.query("docs", embeddings.embed_query(texts[0]), k=2)
    assert len(results) == 2


async def test_query_applies_metadata_filter(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM)
    texts = ["english doc", "german doc"]
    docs = [
        Document(page_content=texts[0], metadata={"lang": "en"}),
        Document(page_content=texts[1], metadata={"lang": "de"}),
    ]
    await store.upsert("docs", docs, _embed(embeddings, texts))
    results = await store.query(
        "docs", embeddings.embed_query(texts[1]), k=5, filter={"lang": "en"}
    )
    assert [r.page_content for r in results] == ["english doc"]


async def test_query_raw_filter_rejected(store: LocalVectorStore) -> None:
    # local has no vendor filter dialect (base.py contract)
    await store.ensure_collection("docs", DIM)
    with pytest.raises(VectorStoreError, match="raw_filter"):
        await store.query("docs", [0.0] * DIM, raw_filter={"x": 1})


async def test_query_filter_null_matches_missing_and_stored_null(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM)
    docs = [
        Document(page_content="null", metadata={"id": "1", "flag": None}),
        Document(page_content="missing", metadata={"id": "2"}),
        Document(page_content="set", metadata={"id": "3", "flag": "yes"}),
    ]
    await store.upsert("docs", docs, _embed(embeddings, ["null", "missing", "set"]))
    hits = await store.query("docs", embeddings.embed_query("null"), k=5, filter={"flag": None})
    assert {h.page_content for h in hits} == {"null", "missing"}


async def test_query_filter_in_with_null_operand(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM)
    docs = [
        Document(page_content="null", metadata={"id": "1", "flag": None}),
        Document(page_content="yes", metadata={"id": "2", "flag": "yes"}),
        Document(page_content="no", metadata={"id": "3", "flag": "no"}),
    ]
    await store.upsert("docs", docs, _embed(embeddings, ["null", "yes", "no"]))
    hits = await store.query(
        "docs", embeddings.embed_query("yes"), k=5, filter={"flag": {"$in": ["yes", None]}}
    )
    assert {h.page_content for h in hits} == {"null", "yes"}


async def test_query_filter_empty_in_matches_nothing(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM)
    await store.upsert("docs", [Document(page_content="a")], _embed(embeddings, ["a"]))
    hits = await store.query("docs", embeddings.embed_query("a"), k=5, filter={"x": {"$in": []}})
    assert hits == []


async def test_query_filter_quoted_key_falls_back_to_python_filter(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    """Keys not embeddable in a JSON path can't go to SQL — the exact Python
    reference filter takes over (never lossy: scoring is brute-force)."""
    key = 'we"ird'
    await store.ensure_collection("docs", DIM)
    docs = [
        Document(page_content="hit", metadata={"id": "1", key: "x"}),
        Document(page_content="miss", metadata={"id": "2", key: "y"}),
    ]
    await store.upsert("docs", docs, _embed(embeddings, ["hit", "miss"]))
    hits = await store.query("docs", embeddings.embed_query("hit"), k=5, filter={key: "x"})
    assert [h.page_content for h in hits] == ["hit"]


async def test_query_score_threshold_excludes_low_matches(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM, metric="cosine")
    texts = ["exact match target", "totally unrelated phrase"]
    docs = [Document(page_content=t) for t in texts]
    await store.upsert("docs", docs, _embed(embeddings, texts))
    # threshold just under 1.0 keeps only the self-match
    results = await store.query(
        "docs", embeddings.embed_query(texts[0]), k=5, score_threshold=0.999
    )
    assert [r.page_content for r in results] == ["exact match target"]


# --------------------------------------------------------------------------- delete
async def test_delete_missing_collection(store: LocalVectorStore) -> None:
    with pytest.raises(CollectionMissing):
        await store.delete("ghost")


async def test_delete_by_ids(store: LocalVectorStore, embeddings: Embeddings) -> None:
    await store.ensure_collection("docs", DIM)
    docs = [
        Document(page_content="a", metadata={"id": "a"}),
        Document(page_content="b", metadata={"id": "b"}),
    ]
    await store.upsert("docs", docs, _embed(embeddings, ["a", "b"]))
    deleted = await store.delete("docs", ids=["a"])
    assert deleted == 1
    infos = await store.list_collections()
    assert infos[0].count == 1


async def test_delete_by_filter(store: LocalVectorStore, embeddings: Embeddings) -> None:
    await store.ensure_collection("docs", DIM)
    docs = [
        Document(page_content="en", metadata={"id": "1", "lang": "en"}),
        Document(page_content="de", metadata={"id": "2", "lang": "de"}),
        Document(page_content="en2", metadata={"id": "3", "lang": "en"}),
    ]
    await store.upsert("docs", docs, _embed(embeddings, ["en", "de", "en2"]))
    deleted = await store.delete("docs", filter={"lang": "en"})
    assert deleted == 2
    remaining = await store.query("docs", embeddings.embed_query("de"), k=5)
    assert [r.page_content for r in remaining] == ["de"]


async def test_delete_filter_quoted_key_falls_back_to_python_filter(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    key = "back\\slash"
    await store.ensure_collection("docs", DIM)
    docs = [
        Document(page_content="a", metadata={"id": "1", key: "x"}),
        Document(page_content="b", metadata={"id": "2", key: "y"}),
    ]
    await store.upsert("docs", docs, _embed(embeddings, ["a", "b"]))
    assert await store.delete("docs", filter={key: "x"}) == 1
    assert (await store.list_collections())[0].count == 1


async def test_delete_all_when_no_ids_or_filter(
    store: LocalVectorStore, embeddings: Embeddings
) -> None:
    await store.ensure_collection("docs", DIM)
    texts = ["one", "two", "three"]
    docs = [Document(page_content=t) for t in texts]
    await store.upsert("docs", docs, _embed(embeddings, texts))
    deleted = await store.delete("docs")
    assert deleted == 3
    infos = await store.list_collections()
    assert infos[0].count == 0
