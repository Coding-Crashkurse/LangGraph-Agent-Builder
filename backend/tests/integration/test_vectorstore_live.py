"""Integration tier (SPEC §4.10): the vector store abstraction against *live*
vendor servers. Everything here is opt-in — a test runs only when its
``LGA_TEST_<BACKEND>_URL`` env var points at a reachable server (docker
compose / testcontainers in the separate CI job), so the default SQLite-tier
run stays green with zero servers and zero extras.

The full cross-backend behaviour matrix lives in
``tests/contract/test_vectorstore_contract.py`` (which already covers qdrant
in-process, chroma embedded, pgvector on :55432 and weaviate via
``LGA_TEST_WEAVIATE_URL``); these smoke tests only pin the *server* connection
paths the contract suite cannot reach without one (url/api_key params).
"""

from __future__ import annotations

import importlib.util
import os

import pytest

from lga.sdk.ports import Document
from lga.vectorstores import build_provider

pytestmark = pytest.mark.integration

DIM = 8
QDRANT_URL = os.environ.get("LGA_TEST_QDRANT_URL")
CHROMA_URL = os.environ.get("LGA_TEST_CHROMA_URL")


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


@pytest.mark.skipif(
    not (QDRANT_URL and _installed("qdrant_client")),
    reason="set LGA_TEST_QDRANT_URL (and install the qdrant extra)",
)
async def test_qdrant_server_round_trip() -> None:
    provider = build_provider("qdrant", "it", {"url": QDRANT_URL})
    try:
        await provider.health()
        await provider.ensure_collection("it_smoke", DIM)
        await provider.upsert(
            "it_smoke", [Document(page_content="alpha")], [[1.0] + [0.0] * (DIM - 1)]
        )
        hits = await provider.query("it_smoke", [1.0] + [0.0] * (DIM - 1), k=1)
        assert hits[0].page_content == "alpha"
        assert await provider.delete("it_smoke") == 1
    finally:
        await provider.aclose()  # type: ignore[attr-defined]  # built-in providers expose aclose


@pytest.mark.skipif(
    not (CHROMA_URL and _installed("chromadb")),
    reason="set LGA_TEST_CHROMA_URL (and install the chroma extra)",
)
async def test_chroma_http_round_trip() -> None:
    from urllib.parse import urlsplit

    parts = urlsplit(CHROMA_URL or "")
    provider = build_provider(
        "chroma",
        "it",
        {"mode": "http", "host": parts.hostname or "localhost", "port": parts.port or 8000},
    )
    try:
        await provider.health()
        await provider.ensure_collection("it_smoke", DIM)
        await provider.upsert(
            "it_smoke", [Document(page_content="alpha")], [[1.0] + [0.0] * (DIM - 1)]
        )
        hits = await provider.query("it_smoke", [1.0] + [0.0] * (DIM - 1), k=1)
        assert hits[0].page_content == "alpha"
        assert await provider.delete("it_smoke") == 1
    finally:
        await provider.aclose()  # type: ignore[attr-defined]  # built-in providers expose aclose
