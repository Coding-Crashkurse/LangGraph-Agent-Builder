"""Unit tests for the pure translation helpers of the vendor vector store
backends (SPEC §8b.2). The vendor clients themselves are exercised by the
contract suite (``tests/contract``) when their extra is installed; the helpers
here are importable *without* any extra (lazy vendor imports) and pin the
parts of the cross-backend contract that need no server: URL/collection-name
normalisation, per-metric score conversion, and native filter translation."""

from __future__ import annotations

import pytest

from langgraph_agent_builder.vectorstores.base import VectorStoreError
from langgraph_agent_builder.vectorstores.chroma import _to_score as chroma_score
from langgraph_agent_builder.vectorstores.chroma import _translate_where
from langgraph_agent_builder.vectorstores.pgvector import _where_sql
from langgraph_agent_builder.vectorstores.qdrant import _distance_value
from langgraph_agent_builder.vectorstores.weaviate import (
    _cname,
    _endpoints,
    _from_cname,
    _parse_desc,
)
from langgraph_agent_builder.vectorstores.weaviate import _to_score as weaviate_score


# --------------------------------------------------------------------------- weaviate endpoints
def test_endpoints_default_url() -> None:
    assert _endpoints({}) == ("localhost", 8080, False, "localhost", 50051, False)


def test_endpoints_https_scheme_aware_default_port() -> None:
    host, port, secure, grpc_host, grpc_port, grpc_secure = _endpoints(
        {"url": "https://cluster.example.com"}
    )
    assert (host, port, secure) == ("cluster.example.com", 443, True)
    assert (grpc_host, grpc_port, grpc_secure) == ("cluster.example.com", 50051, True)


def test_endpoints_http_default_port_and_schemeless_host() -> None:
    assert _endpoints({"url": "http://box"})[:3] == ("box", 80, False)
    assert _endpoints({"url": "box:1234"})[:3] == ("box", 1234, False)


def test_endpoints_grpc_overrides() -> None:
    _, _, _, grpc_host, grpc_port, grpc_secure = _endpoints(
        {"url": "https://a", "grpc_host": "grpc.a", "grpc_port": 4443, "grpc_secure": False}
    )
    assert (grpc_host, grpc_port, grpc_secure) == ("grpc.a", 4443, False)


# --------------------------------------------------------------------------- weaviate names
def test_cname_round_trips_through_weaviate_capitalisation() -> None:
    assert _cname("docs") == "Docs"
    assert _from_cname("Docs") == "docs"
    assert _from_cname(_cname("my_docs2")) == "my_docs2"


@pytest.mark.parametrize("bad", ["Docs", "1docs", "my-docs", ""])
def test_cname_rejects_names_weaviate_would_mangle(bad: str) -> None:
    with pytest.raises(VectorStoreError, match="round-trip"):
        _cname(bad)


def test_parse_desc_round_trip_and_fallbacks() -> None:
    assert _parse_desc("lab:dim=128;metric=l2") == (128, "l2")
    assert _parse_desc(None) == (0, "cosine")
    assert _parse_desc("no marker here") == (0, "cosine")
    assert _parse_desc("lab:dim=8;metric=bogus") == (8, "cosine")


# --------------------------------------------------------------------------- score conversion
def test_weaviate_scores_follow_contract() -> None:
    assert weaviate_score("cosine", 0.25) == pytest.approx(0.75)
    assert weaviate_score("l2", 9.0) == pytest.approx(1.0 / 4.0)  # distance is squared
    assert weaviate_score("ip", -6.0) == pytest.approx(6.0)  # dot distance is negated


def test_chroma_scores_follow_contract() -> None:
    assert chroma_score("cosine", 0.25) == pytest.approx(0.75)
    assert chroma_score("l2", 9.0) == pytest.approx(1.0 / 4.0)  # distance is squared
    assert chroma_score("ip", 1.0 - 6.0) == pytest.approx(6.0)  # ip distance is 1-dot


# --------------------------------------------------------------------------- chroma filters
def test_chroma_translate_where_single_and_multi_clause() -> None:
    assert _translate_where(None) is None
    assert _translate_where({"lang": "en"}) == {"lang": {"$eq": "en"}}
    assert _translate_where({"$and": [{"lang": "en"}, {"n": {"$in": [1, 2]}}]}) == {
        "$and": [{"lang": {"$eq": "en"}}, {"n": {"$in": [1, 2]}}]
    }


def test_chroma_translate_where_rejects_non_scalars() -> None:
    with pytest.raises(VectorStoreError, match="unsupported filter value"):
        _translate_where({"lang": None})
    with pytest.raises(VectorStoreError, match="unsupported filter values"):
        _translate_where({"n": {"$in": [1, None]}})


# --------------------------------------------------------------------------- pgvector filters
def test_pgvector_where_sql_eq_and_in_with_param_numbering() -> None:
    where, params = _where_sql({"lang": "en", "n": {"$in": [1, 2]}}, start=3)
    assert "$3" in where
    assert "$6" in where
    assert params == ["lang", '"en"', "n", ["1", "2"]]


def test_pgvector_where_sql_null_matches_missing_and_stored_null() -> None:
    where, params = _where_sql({"flag": None}, start=1)
    assert "IS NULL" in where
    assert "'null'::jsonb" in where
    assert params == ["flag"]


def test_pgvector_where_sql_empty_filter() -> None:
    assert _where_sql(None, start=1) == ("", [])


# --------------------------------------------------------------------------- qdrant metrics
def test_qdrant_distance_value_reads_enum_string_or_default() -> None:
    class _Enum:
        value = "Euclid"

    class _Vectors:
        distance = _Enum()

    class _Plain:
        distance = "Dot"

    assert _distance_value(_Vectors()) == "Euclid"
    assert _distance_value(_Plain()) == "Dot"
    assert _distance_value(object()) == "Cosine"
