"""Unit tests for the surviving RAG helpers (SPEC §12.4 / §8b).

Only the shared ``_embeddings`` / ``_provider`` plumbing (used by kb_retriever)
remains here; the retriever/writer/splitter/file-loader component classes were
retired. The ingest→search happy path is covered by ``test_new_palette_nodes``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from langgraph_agent_builder.components.rag.components import _embeddings, _provider
from langgraph_agent_builder.sdk.ports import VectorStoreHandle

if TYPE_CHECKING:
    from collections.abc import Iterator

    from langgraph_agent_builder.services.settings import Settings


# ------------------------------------------------------------------- infra
@pytest.fixture(autouse=True)
def _headless() -> Iterator[None]:
    """Force the module onto the headless (direct local provider) path by
    clearing the process-wide service locator, restoring it afterwards."""
    from langgraph_agent_builder.services import locator

    saved = locator.get_services()
    locator.set_services(None)
    try:
        yield
    finally:
        locator.set_services(saved)


# ------------------------------------------------------------------- _embeddings
def test_embeddings_resolves_fake_dim() -> None:
    emb = _embeddings({"provider": "fake", "dim": 8})
    assert emb.size == 8  # type: ignore[attr-defined]
    # None → default fake provider
    default = _embeddings(None)
    assert default.size == 32  # type: ignore[attr-defined]


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
    from langgraph_agent_builder.services import locator

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

    monkeypatch.setattr("langgraph_agent_builder.services.locator.get_services", _boom)
    handle = VectorStoreHandle(connection="local")
    resolved = await _provider(handle, sqlite_settings)
    assert resolved.backend == "local"
