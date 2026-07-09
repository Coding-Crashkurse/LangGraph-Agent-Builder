"""Unit tests for the RAG catalog (SPEC §12.4 / §8b).

Drives the retriever/writer/embeddings/splitter/file-loader NodeFns directly
against the in-process ``local`` (sqlite) vector backend with ``fake``
deterministic embeddings. Covers the ingest→search happy path plus the
RT107 error branches, the portable metadata filter, the empty-docs dim
fallback, the pure-Python splitter recursion, the file-loader dispatch, the
``_provider`` service-locator branch, and the legacy migrate_config maps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from lga.components.rag.components import (
    Embeddings,
    FileLoader,
    PgvectorRetriever,
    PgvectorWriter,
    TextSplitter,
    VectorRetriever,
    VectorWriter,
    _as_document,
    _embeddings,
    _handle,
    _load_file,
    _provider,
    _split,
)
from lga.schema.diagnostics import RuntimeError_, RuntimeErrorCode
from lga.sdk.component import BuildContext, InputBinding, SecretsResolver
from lga.sdk.ports import Document, VectorStoreHandle
from lga.sdk.testing import BuiltNode
from lga.vectorstores import build_provider

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lga.services.settings import Settings


# ------------------------------------------------------------------- infra
@pytest.fixture(autouse=True)
def _headless() -> Iterator[None]:
    """Force the module onto the headless (direct local provider) path by
    clearing the process-wide service locator, restoring it afterwards."""
    from lga.services import locator

    saved = locator.get_services()
    locator.set_services(None)
    try:
        yield
    finally:
        locator.set_services(saved)


def _build(
    component: type[Any],
    settings: Settings | None = None,
    config: dict[str, Any] | None = None,
    port_values: dict[str, Any] | None = None,
    node_id: str = "under_test",
) -> BuiltNode:
    """Build a NodeFn with a stub BuildContext that carries real Settings so
    the RAG nodes resolve a local provider under the test's tmp home."""
    bindings = {
        name: InputBinding(input_name=name, channel=None, constant=value)
        for name, value in (port_values or {}).items()
    }
    ctx = BuildContext(
        node_id=node_id,
        flow_id="test-flow",
        label=component.display_name or node_id,
        config=dict(config or {}),
        secrets=SecretsResolver({}),
        input_bindings=bindings,
        settings=settings,
    )
    return BuiltNode(component().build(ctx), ctx)


def _vs(collection: str, connection: str = "local") -> dict[str, Any]:
    return {"$vectorstore": connection, "collection": collection}


async def _ingest(settings: Settings, collection: str, docs: list[dict[str, Any]]) -> None:
    writer = _build(
        VectorWriter,
        settings,
        config={"vector_store": _vs(collection)},
        port_values={"documents": docs, "embedding": {"provider": "fake", "dim": 32}},
    )
    await writer()


# ------------------------------------------------------------------- helpers
def test_handle_passthrough_dict_and_default() -> None:
    handle = VectorStoreHandle(connection="c1", collection="col")
    assert _handle(handle) is handle

    from_ref = _handle({"$vectorstore": "conn", "collection": "kb"})
    assert from_ref.connection == "conn"
    assert from_ref.collection == "kb"

    from_conn = _handle({"connection": "other"})
    assert from_conn.connection == "other"
    assert from_conn.collection is None

    assert _handle({}).connection == "local"
    assert _handle(None).connection == "local"
    assert _handle(42).connection == "local"


def test_embeddings_resolves_fake_dim() -> None:
    emb = _embeddings({"provider": "fake", "dim": 8})
    assert emb.size == 8  # type: ignore[attr-defined]
    # None → default fake provider
    default = _embeddings(None)
    assert default.size == 32  # type: ignore[attr-defined]


def test_as_document_variants() -> None:
    doc = Document(page_content="already")
    assert _as_document(doc) is doc

    from_dict = _as_document({"page_content": "body", "metadata": {"k": "v"}})
    assert from_dict.page_content == "body"
    assert from_dict.metadata == {"k": "v"}

    from_str = _as_document("plain")
    assert from_str.page_content == "plain"
    assert from_str.metadata == {}


# ------------------------------------------------------------------- writer + retriever
async def test_write_then_retrieve_roundtrip(sqlite_settings: Settings) -> None:
    await _ingest(
        sqlite_settings,
        "kb",
        [
            {"page_content": "the cat sat on the mat", "metadata": {"source": "a"}},
            {"page_content": "dogs are loyal companions", "metadata": {"source": "b"}},
        ],
    )
    retriever = _build(
        VectorRetriever,
        sqlite_settings,
        config={"vector_store": _vs("kb"), "k": 5, "query": "cat"},
    )
    result = await retriever()
    docs = result["documents"]
    assert {d.page_content for d in docs} == {
        "the cat sat on the mat",
        "dogs are loyal companions",
    }
    assert all(isinstance(d, Document) and d.score is not None for d in docs)


async def test_writer_reports_written_count(sqlite_settings: Settings) -> None:
    writer = _build(
        VectorWriter,
        sqlite_settings,
        config={"vector_store": _vs("counts")},
        port_values={
            "documents": ["one", "two", "three"],
            "embedding": {"provider": "fake", "dim": 16},
        },
    )
    result = await writer()
    assert result["json"] == {"written": 3, "collection": "counts"}
    assert result["data"] == {"ingested": 3}


async def test_writer_empty_documents_uses_dim_fallback(sqlite_settings: Settings) -> None:
    # no documents → vectors empty → dim comes from embedding_cfg fallback (32)
    writer = _build(
        VectorWriter,
        sqlite_settings,
        config={"vector_store": _vs("empty")},
    )
    result = await writer()
    assert result["json"] == {"written": 0, "collection": "empty"}
    # collection was still created at the fallback dimension
    provider = build_provider("local", "local", home=sqlite_settings.home)
    infos = {c.name: c for c in await provider.list_collections()}
    assert infos["empty"].dim == 32


async def test_retriever_metadata_filter(sqlite_settings: Settings) -> None:
    await _ingest(
        sqlite_settings,
        "filtered",
        [
            {"page_content": "alpha doc", "metadata": {"source": "x"}},
            {"page_content": "beta doc", "metadata": {"source": "y"}},
        ],
    )
    retriever = _build(
        VectorRetriever,
        sqlite_settings,
        config={"vector_store": _vs("filtered"), "query": "doc", "filter": {"source": "x"}},
    )
    docs = (await retriever())["documents"]
    assert [d.page_content for d in docs] == ["alpha doc"]


async def test_retriever_score_threshold_enforced(sqlite_settings: Settings) -> None:
    await _ingest(
        sqlite_settings,
        "scored",
        [{"page_content": "content here", "metadata": {}}],
    )
    retriever = _build(
        VectorRetriever,
        sqlite_settings,
        config={"vector_store": _vs("scored"), "query": "content", "score_threshold": 0.0},
    )
    docs = (await retriever())["documents"]
    assert all((d.score or -1.0) >= 0.0 for d in docs)


async def test_retriever_query_falls_back_to_message(sqlite_settings: Settings) -> None:
    await _ingest(
        sqlite_settings,
        "msgkb",
        [{"page_content": "fallback body", "metadata": {}}],
    )
    from langchain_core.messages import HumanMessage

    retriever = _build(
        VectorRetriever,
        sqlite_settings,
        config={"vector_store": _vs("msgkb")},
    )
    docs = (await retriever({"messages": [HumanMessage(content="ask something")]}))["documents"]
    assert [d.page_content for d in docs] == ["fallback body"]


async def test_retriever_missing_collection_raises_rt107(sqlite_settings: Settings) -> None:
    retriever = _build(
        VectorRetriever,
        sqlite_settings,
        config={"vector_store": _vs("does-not-exist"), "query": "x"},
        node_id="retr",
    )
    with pytest.raises(RuntimeError_) as excinfo:
        await retriever()
    assert excinfo.value.code == RuntimeErrorCode.RT107
    assert excinfo.value.node_id == "retr"


async def test_writer_dimension_mismatch_raises_rt107(sqlite_settings: Settings) -> None:
    # pre-create the collection at dim 8; writer's fake embeddings are dim 32
    provider = build_provider("local", "local", home=sqlite_settings.home)
    await provider.ensure_collection("mismatch", 8)

    writer = _build(
        VectorWriter,
        sqlite_settings,
        config={"vector_store": _vs("mismatch")},
        port_values={"documents": ["hello"], "embedding": {"provider": "fake", "dim": 32}},
        node_id="wr",
    )
    with pytest.raises(RuntimeError_) as excinfo:
        await writer()
    assert excinfo.value.code == RuntimeErrorCode.RT107
    assert excinfo.value.node_id == "wr"


async def test_retriever_health_check_ok(sqlite_settings: Settings) -> None:
    comp = VectorRetriever()
    ctx = BuildContext(
        node_id="h",
        config={"vector_store": _vs("health")},
        settings=sqlite_settings,
    )
    # local backend health() connects & closes without raising
    await comp.health_check(ctx)


# ------------------------------------------------------------------- embeddings component
async def test_embeddings_component_emits_serializable_config() -> None:
    node = _build(Embeddings, config={"model": {"provider": "fake", "dim": 64}})
    result = await node()
    assert result["embedding"] == {"provider": "fake", "dim": 64}


async def test_embeddings_component_defaults_to_fake() -> None:
    node = _build(Embeddings)
    result = await node()
    assert result["embedding"] == {"provider": "fake"}


# ------------------------------------------------------------------- text splitter
async def test_text_splitter_splits_inbound_text() -> None:
    node = _build(
        TextSplitter,
        config={"chunk_size": 50, "chunk_overlap": 10},
        port_values={"text": "First sentence. Second sentence. Third sentence here."},
    )
    docs = (await node())["documents"]
    assert docs
    assert all(isinstance(d, Document) for d in docs)
    assert all(len(d.page_content) <= 50 for d in docs)


async def test_text_splitter_carries_document_metadata() -> None:
    node = _build(
        TextSplitter,
        config={"chunk_size": 60, "chunk_overlap": 5},
        port_values={
            "documents": [
                {"page_content": "para one.\n\npara two is here.", "metadata": {"src": "d"}}
            ]
        },
    )
    docs = (await node())["documents"]
    assert docs
    assert all(d.metadata == {"src": "d"} for d in docs)


def test_split_empty_returns_no_chunks() -> None:
    assert _split("   ", 50, 10) == []


def test_split_long_unbroken_text_char_chunks() -> None:
    # no separators at all → falls through to fixed-width char chunking
    text = "x" * 200
    chunks = _split(text, 50, 10)
    assert len(chunks) > 1
    assert all(len(c) <= 50 for c in chunks)
    assert "".join(chunks[:1])  # non-empty first chunk


def test_split_trailing_empty_segment_leaves_no_blank_chunk() -> None:
    # a long token followed by a space produces an internal empty segment at the
    # " " level; the splitter must not emit a blank chunk for it.
    text = "A" * 60 + " . end"
    chunks = _split(text, 50, 10)
    assert chunks
    assert all(c.strip() for c in chunks)


# ------------------------------------------------------------------- file loader
class _Row:
    def __init__(self, name: str, mime: str) -> None:
        self.name = name
        self.mime = mime


class _FakeFiles:
    def __init__(self, store: dict[str, tuple[_Row, bytes]]) -> None:
        self._store = store

    async def get(self, file_id: str) -> tuple[_Row, bytes] | None:
        return self._store.get(file_id)


class _FakeServices:
    def __init__(self, files: _FakeFiles) -> None:
        self.files = files


async def test_file_loader_requires_services() -> None:
    node = _build(FileLoader, config={"files": ["f1"]})
    with pytest.raises(RuntimeError, match="file_loader requires a running lga server"):
        await node()


async def test_file_loader_loads_txt_and_skips_missing() -> None:
    from lga.services import locator

    store = {"good": (_Row("note.txt", "text/plain"), b"hello world")}
    locator.set_services(_FakeServices(_FakeFiles(store)))
    node = _build(FileLoader, config={"files": ["good", "missing"]})
    docs = (await node())["documents"]
    assert [d.page_content for d in docs] == ["hello world"]
    assert docs[0].metadata == {"source": "note.txt"}


async def test_file_loader_reads_file_refs_port() -> None:
    from lga.services import locator

    store = {"r1": (_Row("data.txt", "text/plain"), b"from ref")}
    locator.set_services(_FakeServices(_FakeFiles(store)))
    node = _build(
        FileLoader,
        # a ref without a file_id is skipped; the valid one is loaded
        port_values={"file_refs": [{"file_id": "r1"}, {"note": "no id"}]},
    )
    docs = (await node())["documents"]
    assert [d.page_content for d in docs] == ["from ref"]


def test_load_file_csv() -> None:
    content = b"name,age\nalice,30\nbob,25\n"
    docs = _load_file("people.csv", "text/csv", content)
    assert len(docs) == 2
    assert "name: alice" in docs[0].page_content
    assert docs[0].metadata == {"source": "people.csv", "row": 0}


def test_load_file_json_list_and_object() -> None:
    as_list = _load_file("items.json", "application/json", b'[{"a": 1}, {"a": 2}]')
    assert len(as_list) == 2
    assert as_list[1].metadata == {"source": "items.json", "index": 1}

    as_obj = _load_file("one.json", "application/json", b'{"k": "v"}')
    assert len(as_obj) == 1
    assert as_obj[0].metadata == {"source": "one.json", "index": 0}


def test_load_file_pdf_branch() -> None:
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    docs = _load_file("doc.pdf", "application/pdf", buf.getvalue())
    assert len(docs) == 1
    assert docs[0].metadata == {"source": "doc.pdf"}


# ------------------------------------------------------------------- _provider locator branch
class _SentinelProvider:
    backend = "local"


class _FakeVectorstores:
    def __init__(self, provider_obj: _SentinelProvider) -> None:
        self._provider = provider_obj

    async def provider(self, connection: str) -> _SentinelProvider:
        assert connection == "myconn"
        return self._provider


class _VsServices:
    def __init__(self, vectorstores: _FakeVectorstores) -> None:
        self.vectorstores = vectorstores


async def test_provider_uses_service_locator_when_available() -> None:
    from lga.services import locator

    sentinel = _SentinelProvider()
    locator.set_services(_VsServices(_FakeVectorstores(sentinel)))
    handle = VectorStoreHandle(connection="myconn")
    resolved = await _provider(handle, None)
    assert id(resolved) == id(sentinel)


async def test_provider_falls_back_to_local_when_locator_raises(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> Any:
        raise RuntimeError("locator unavailable")

    monkeypatch.setattr("lga.services.locator.get_services", _boom)
    handle = VectorStoreHandle(connection="local")
    resolved = await _provider(handle, sqlite_settings)
    assert resolved.backend == "local"


# ------------------------------------------------------------------- legacy migrate_config
def test_pgvector_retriever_migrate_config() -> None:
    migrated = PgvectorRetriever.migrate_config("0.9", {"collection": "old_kb", "k": 3})
    assert migrated["vector_store"] == {"$vectorstore": "local", "collection": "old_kb"}
    assert "collection" not in migrated
    assert migrated["k"] == 3


def test_pgvector_writer_migrate_config() -> None:
    migrated = PgvectorWriter.migrate_config("0.9", {"collection": "docs"})
    assert migrated["vector_store"] == {"$vectorstore": "local", "collection": "docs"}
    assert "collection" not in migrated
