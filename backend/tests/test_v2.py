"""v2 coverage: vector stores, partial runs, Table, slug-first, lock, upgrade,
templates, migration, tool events (SPEC §8b, §6.4, §4.3, §9, §4.11, §9.9)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, cast

import pytest

from langgraph_agent_builder.sdk.ports import (
    JSON,
    TABLE,
    TEXT,
    Document,
    VectorStoreHandle,
    check_compatibility,
    coerce,
)

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from langgraph_agent_builder.app import AppServices
    from langgraph_agent_builder.compiler.ir import FlowIR


# --------------------------------------------------------------------------- Table type
def test_table_family_and_coercions() -> None:
    assert TABLE.family.value == "TABLE"
    # Table → Json / Text are registered coercions
    assert check_compatibility(TABLE, JSON).compatible
    assert check_compatibility(TABLE, TEXT).compatible
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert coerce.apply("table_to_json", rows) == {"rows": rows}
    md = coerce.apply("table_to_text", rows)
    assert "| a | b |" in md
    assert "| 1 | 2 |" in md


def test_vectorstore_port_family() -> None:
    from langgraph_agent_builder.sdk.ports import VECTOR_STORE

    assert VECTOR_STORE.family.value == "VECTORSTORE"


# --------------------------------------------------------------------------- migration
def test_flowspec_v1_to_v2_migration() -> None:
    from langgraph_agent_builder.schema.flowspec import parse_flowspec

    spec = parse_flowspec(
        {
            "schema_version": "1",
            "flow": {"name": "x", "slug": "x"},
            "nodes": [{"id": "start", "component_id": "lab.io.start"}],
        }
    )
    assert spec.schema_version == "2"
    assert spec.flow.locked is False
    assert spec.flow.mcp.enabled is False


# --------------------------------------------------------------------------- local backend
async def test_local_vector_store_roundtrip(tmp_path: Path) -> None:
    from langgraph_agent_builder.vectorstores import build_provider

    provider = build_provider("local", "unit", {}, home=tmp_path)
    await provider.health()
    await provider.ensure_collection("docs", dim=3, metric="cosine")
    docs = [
        Document(page_content="alpha", metadata={"id": "1", "tag": "x"}),
        Document(page_content="beta", metadata={"id": "2", "tag": "y"}),
    ]
    result = await provider.upsert("docs", docs, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    assert result.count == 2
    hits = await provider.query("docs", [1.0, 0.0, 0.0], k=1)
    assert hits
    assert hits[0].page_content == "alpha"
    assert hits[0].score is not None
    # portable filter subset
    filtered = await provider.query("docs", [0.0, 1.0, 0.0], k=5, filter={"tag": "y"})
    assert [d.page_content for d in filtered] == ["beta"]
    # $in filter
    both = await provider.query("docs", [1.0, 0.0, 0.0], k=5, filter={"tag": {"$in": ["x", "y"]}})
    assert len(both) == 2
    assert await provider.delete("docs", ids=["1"]) == 1
    assert len(await provider.list_collections()) == 1


async def test_local_dimension_mismatch(tmp_path: Path) -> None:
    from langgraph_agent_builder.vectorstores import DimensionMismatch, build_provider

    provider = build_provider("local", "dim", {}, home=tmp_path)
    await provider.ensure_collection("c", dim=3)
    with pytest.raises(DimensionMismatch):
        await provider.upsert("c", [Document(page_content="x")], [[1.0, 2.0]])


async def test_backend_extra_missing(tmp_path: Path) -> None:
    from langgraph_agent_builder.vectorstores import BackendExtraMissing, build_provider

    provider = build_provider("qdrant", "q", {"url": "http://localhost:1"})
    # qdrant-client is not installed in the base test env → E901 path
    if "qdrant_client" not in sys.modules:
        try:
            import qdrant_client  # noqa: F401

            pytest.skip("qdrant-client installed")
        except ImportError:
            with pytest.raises(BackendExtraMissing):
                await provider.health()


def test_import_lga_does_not_import_vendor_clients() -> None:
    # importing lab must never pull in a vendor vector client (SPEC §8b.2)
    import importlib

    importlib.import_module("langgraph_agent_builder")
    importlib.import_module("langgraph_agent_builder.vectorstores")
    for vendor in ("qdrant_client", "weaviate", "chromadb"):
        assert vendor not in sys.modules, f"{vendor} imported at lab import time"


# --------------------------------------------------------------------------- compiler
def test_vectorstore_ref_resolves_to_handle_and_e013() -> None:
    from langgraph_agent_builder.compiler import compile_flow

    def spec(conn: str) -> dict[str, Any]:
        return {
            "schema_version": "2",
            "flow": {"name": "r", "slug": "r"},
            "nodes": [
                {"id": "start", "component_id": "lab.io.start"},
                {
                    "id": "emb",
                    "component_id": "lab.testing.fake_embeddings",
                    "config": {"dim": 8},
                },
                {
                    "id": "ret",
                    "component_id": "lab.rag.retriever",
                    "config": {"vector_store": {"$vectorstore": conn, "collection": "c"}},
                },
                {"id": "end", "component_id": "lab.io.end"},
            ],
            "edges": [
                {
                    "id": "e0",
                    "kind": "data",
                    "source": {"node": "start", "output": "message"},
                    "target": {"node": "ret", "input": "query_port"},
                },
                {
                    "id": "e1",
                    "kind": "data",
                    "source": {"node": "emb", "output": "embedding"},
                    "target": {"node": "ret", "input": "embedding"},
                },
                {
                    "id": "e2",
                    "kind": "data",
                    "source": {"node": "ret", "output": "documents"},
                    "target": {"node": "end", "input": "text"},
                },
            ],
        }

    ok = compile_flow(spec("local"), vectorstore_names={"local"})
    handle = ok.node_contexts["ret"].get_field("vector_store")
    assert isinstance(handle, VectorStoreHandle)
    assert handle.connection == "local"
    assert handle.collection == "c"

    bad = compile_flow(spec("ghost"), vectorstore_names={"local"})
    assert any(d.code.value == "E013" for d in bad.diagnostics)


def test_partial_run_subgraph_induction() -> None:
    from langgraph_agent_builder.compiler import compile_flow
    from langgraph_agent_builder.compiler.subgraph import ancestors_of, induce_subgraph
    from tests.conftest import hello_spec

    compiled = compile_flow(hello_spec())
    assert ancestors_of(cast("FlowIR", compiled.ir), "fake") == {"start", "fake"}
    sub = induce_subgraph(compiled, "fake")
    sub_ir = cast("FlowIR", sub.ir)
    assert set(sub_ir.nodes) == {"start", "fake"}
    assert "end" not in sub_ir.nodes


# --------------------------------------------------------------------------- API (server)
async def test_slug_first_and_lock(client: httpx.AsyncClient) -> None:
    spec = {
        "schema_version": "2",
        "flow": {"name": "Locky", "slug": "locky"},
        "nodes": [
            {"id": "start", "component_id": "lab.io.start"},
            {"id": "end", "component_id": "lab.io.end"},
        ],
        "edges": [
            {
                "id": "e",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "end", "input": "message"},
            }
        ],
    }
    created = (await client.post("/api/v1/flows", json={"spec": spec})).json()
    # slug-first: fetch by slug, not just UUID
    by_slug = await client.get("/api/v1/flows/locky")
    assert by_slug.status_code == 200
    assert by_slug.json()["id"] == created["id"]
    # lock blocks PATCH
    assert (await client.post("/api/v1/flows/locky/lock", json={"locked": True})).status_code == 200
    patched = await client.patch("/api/v1/flows/locky", json={"spec": spec})
    assert patched.status_code == 409
    # unlock re-enables editing
    await client.post("/api/v1/flows/locky/lock", json={"locked": False})
    assert (await client.patch("/api/v1/flows/locky", json={"spec": spec})).status_code == 200


async def test_vectorstores_api_default_local(client: httpx.AsyncClient) -> None:
    conns = (await client.get("/api/v1/vectorstores")).json()
    names = {c["name"] for c in conns}
    assert "local" in names  # auto-provisioned default (§8b.3)
    local = next(c for c in conns if c["name"] == "local")
    assert local["backend"] == "local"
    assert local["ok"] is True
    # create a collection
    r = await client.post(
        "/api/v1/vectorstores/local/collections", json={"name": "api_c", "dim": 4}
    )
    assert r.status_code == 201
    cols = (await client.get("/api/v1/vectorstores/local/collections")).json()
    assert any(c["name"] == "api_c" for c in cols)
    backends = (await client.get("/api/v1/vectorstores/backends")).json()
    assert "local" in backends["installed"]


async def test_templates_api(client: httpx.AsyncClient) -> None:
    templates = (await client.get("/api/v1/templates")).json()
    assert templates
    assert any(t["id"] == "starter-hello" for t in templates)
    created = await client.post("/api/v1/flows/from-template/starter-hello")
    assert created.status_code == 201
    assert created.json()["slug"] != "starter-hello"  # fresh unique slug


async def test_node_upgrade_endpoint(client: httpx.AsyncClient) -> None:
    # legacy pgvector node → migrate_config re-pins to installed version
    spec = {
        "schema_version": "2",
        "flow": {"name": "up", "slug": "upflow"},
        "nodes": [
            {"id": "start", "component_id": "lab.io.start"},
            {
                "id": "pg",
                "component_id": "lab.rag.pgvector_retriever",
                "component_version": "0.9.0",
                "config": {"collection": "old"},
            },
            {"id": "end", "component_id": "lab.io.end"},
        ],
        "edges": [],
    }
    await client.post("/api/v1/flows", json={"spec": spec})
    r = await client.post("/api/v1/flows/upflow/nodes/pg/upgrade")
    assert r.status_code == 200
    node = next(n for n in r.json()["flow"]["spec"]["nodes"] if n["id"] == "pg")
    assert node["config"]["vector_store"]["$vectorstore"] == "local"
    assert node["config"]["vector_store"]["collection"] == "old"


async def test_rag_end_to_end_local(client: httpx.AsyncClient, svc: AppServices) -> None:
    # seed the local store, then retrieve via a partial run (§6.4 + §8b)
    provider = await svc.vectorstores.provider("local")
    await provider.ensure_collection("kb", dim=32)
    from langgraph_agent_builder.components.llm._models import resolve_embeddings

    emb = resolve_embeddings({"provider": "fake", "dim": 32})
    texts = ["the sky is blue", "grass is green", "snow is white"]
    vecs = [list(v) for v in await emb.aembed_documents(texts)]
    await provider.upsert(
        "kb", [Document(page_content=t, metadata={"id": str(i)}) for i, t in enumerate(texts)], vecs
    )
    spec = {
        "schema_version": "2",
        "flow": {"name": "rag", "slug": "raglocal"},
        "nodes": [
            {"id": "start", "component_id": "lab.io.start"},
            {"id": "emb", "component_id": "lab.testing.fake_embeddings", "config": {"dim": 32}},
            {
                "id": "ret",
                "component_id": "lab.rag.retriever",
                "config": {"vector_store": {"$vectorstore": "local", "collection": "kb"}, "k": 2},
            },
            {"id": "end", "component_id": "lab.io.end"},
        ],
        "edges": [
            {
                "id": "e0",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "ret", "input": "query_port"},
            },
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "emb", "output": "embedding"},
                "target": {"node": "ret", "input": "embedding"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "ret", "output": "documents"},
                "target": {"node": "end", "input": "text"},
            },
        ],
    }
    await client.post("/api/v1/flows", json={"spec": spec})
    # partial run to the retriever node returns its documents
    resp = await client.post(
        "/api/v1/flows/raglocal/run",
        json={"input_text": "grass is green", "until_node": "ret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert "grass is green" in (body["result_text"] or "")
