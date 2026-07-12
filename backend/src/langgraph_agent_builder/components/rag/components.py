"""RAG helpers (SPEC §12.4) — shared vector-store plumbing for kb_retriever.

The retriever/writer/embeddings component classes were retired; only the
provider/embedding resolution helpers survive here, imported by
:mod:`langgraph_agent_builder.components.rag.kb_retriever`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from langgraph_agent_builder.sdk.ports import VectorStoreHandle

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings as LangchainEmbeddings

    from langgraph_agent_builder.vectorstores.base import VectorStoreProvider


def _services() -> Any:
    """Best-effort service locator: the running server's services, else None."""
    try:
        from langgraph_agent_builder.services.locator import get_services

        return get_services()
    except Exception:
        return None


async def _provider(handle: VectorStoreHandle, settings: Any) -> VectorStoreProvider:
    """Resolve a live provider for a connection — via services when the server
    is up, else a direct ``local`` provider (headless / ``--local`` runs)."""
    svc = _services()
    if svc is not None and getattr(svc, "vectorstores", None) is not None:
        return cast("VectorStoreProvider", await svc.vectorstores.provider(handle.connection))
    from langgraph_agent_builder.services.settings import get_settings
    from langgraph_agent_builder.vectorstores import build_provider

    st = settings or get_settings()
    return build_provider("local", handle.connection, {}, home=st.home)


def _embeddings(value: Any) -> LangchainEmbeddings:
    from langgraph_agent_builder.components.llm._models import resolve_embeddings

    return resolve_embeddings(value or {"provider": "fake"})
