"""Contract test: the built-in ``local`` backend must structurally satisfy the
``VectorStoreProvider`` protocol (SPEC §8b.1).

Rather than asserting the shape method-by-method, we lean on the
``@runtime_checkable`` protocol for structural conformance and then drive one
full create → upsert → query → health round-trip through the same object, so a
future backend added via :func:`build_provider` inherits the same guarantees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lga.components.llm._models import resolve_embeddings
from lga.sdk.ports import Document
from lga.vectorstores import build_provider
from lga.vectorstores.base import CollectionInfo, VectorStoreError, VectorStoreProvider

if TYPE_CHECKING:
    from pathlib import Path

DIM = 8


def test_local_backend_satisfies_provider_protocol(tmp_path: Path) -> None:
    provider = build_provider("local", "contract", home=tmp_path)
    # runtime_checkable structural conformance (SPEC §8b.1)
    assert isinstance(provider, VectorStoreProvider)
    assert provider.backend == "local"


async def test_provider_round_trip(tmp_path: Path) -> None:
    provider = build_provider("local", "contract", home=tmp_path)
    embeddings = resolve_embeddings({"provider": "fake", "dim": DIM})

    # health_check: a fresh backend is reachable
    await provider.health()

    await provider.ensure_collection("kb", DIM, metric="cosine")
    listed = await provider.list_collections()
    assert [c.name for c in listed] == ["kb"]
    assert isinstance(listed[0], CollectionInfo)

    texts = ["retrieval augmented generation", "a poem about the sea"]
    docs = [Document(page_content=t, metadata={"id": t}) for t in texts]
    result = await provider.upsert("kb", docs, embeddings.embed_documents(texts))
    assert result.count == 2
    assert set(result.ids) == set(texts)

    hits = await provider.query("kb", embeddings.embed_query(texts[0]), k=1)
    assert len(hits) == 1
    assert hits[0].page_content == texts[0]
    assert hits[0].score is not None


def test_build_provider_unknown_backend_raises(tmp_path: Path) -> None:
    with pytest.raises(VectorStoreError, match="unknown vector store backend"):
        build_provider("nope", "x", home=tmp_path)
