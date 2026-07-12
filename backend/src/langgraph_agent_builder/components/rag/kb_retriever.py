"""Knowledge Base Retriever — resource-backed similarity search (palette v2).

The successor of :class:`~langgraph_agent_builder.components.rag.components.VectorRetriever`
(and the legacy pgvector retriever): instead of an inline Vector Store Connection
+ Embedding port, it references a single **``knowledge_base`` Resource** that
bundles the vector store connection, collection, and embedding config. The
retrieval itself reuses the existing VectorRetriever plumbing (``_embeddings`` /
``_provider``).
"""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.components.rag.components import _embeddings, _provider
from langgraph_agent_builder.sdk import Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import BuildContext, NodeFn
from langgraph_agent_builder.sdk.ports import VectorStoreHandle
from langgraph_agent_builder.sdk.runtime import get_run_context
from langgraph_agent_builder.sdk.templating import last_message_text


def _kb_ref_parts(value: Any) -> tuple[str, dict[str, Any]]:
    """Recover ``(resource_name, payload)`` from a knowledge_base ResourceHandle
    or its dict/ref form."""
    from langgraph_agent_builder.sdk.ports import ResourceHandle

    if isinstance(value, ResourceHandle):
        return value.name, dict(value.payload)
    if isinstance(value, dict):
        name = str(value.get("$resource") or value.get("name") or "")
        payload = {
            k: v
            for k, v in value.items()
            if k not in ("$resource", "name", "resource_type", "payload")
        }
        nested = value.get("payload")
        if isinstance(nested, dict):
            payload.update(nested)
        return name, payload
    return "", {}


async def _kb_config(name: str) -> dict[str, Any] | None:
    from langgraph_agent_builder.services.locator import get_services

    svc = get_services()
    if svc is None or getattr(svc, "resources", None) is None:
        return None
    result = await svc.resources.resolved_config("knowledge_base", name)
    return result if isinstance(result, dict) else None


class KbRetriever(Component):
    component_id = "lab.rag.kb_retriever"
    display_name = "Knowledge Base"
    description = "Similarity search over a Knowledge Base resource → Documents."
    icon = "search"
    category = "rag"
    priority = 10
    tool_mode_supported = True

    inputs = [
        fields.ResourceRefInput(
            name="knowledge_base",
            display_name="Knowledge Base",
            resource_type="knowledge_base",
            required=True,
            info="A knowledge base resource (vector store connection + collection + embedding).",
        ),
        fields.IntInput(name="k", display_name="Top K", default=4, min=1, max=50),
        # Query is a connectable TEXT input (wire a Chat Input / upstream text in),
        # not a global-variable slot — it also accepts typed text and falls back to
        # the last human message when left unconnected.
        fields.QueryInput(
            name="query",
            display_name="Query",
            as_port=ports.TEXT,
            accepts_global_variable=False,
            tool_mode=True,
        ),
        fields.NestedDictInput(name="filter", display_name="Metadata Filter", advanced=True),
        fields.FloatInput(
            name="score_threshold", display_name="Score Threshold", advanced=True, min=0.0, max=1.0
        ),
        fields.NestedDictInput(
            name="raw_filter",
            display_name="Raw Filter",
            info="Backend-specific filter passthrough (emits W204).",
            advanced=True,
        ),
    ]
    outputs = [Output(name="documents", display_name="Documents", port=ports.DOCUMENTS)]

    def build(self, ctx: BuildContext) -> NodeFn:
        settings = ctx.settings

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            name, payload = _kb_ref_parts(ctx.get_field("knowledge_base"))
            kb_cfg = await _kb_config(name)
            if kb_cfg is None:
                # headless / test: the handle payload may carry the KB config inline
                kb_cfg = payload
            connection = str(kb_cfg.get("vectorstore") or "local")
            collection = payload.get("collection") or kb_cfg.get("collection") or "default"
            embedding_cfg = kb_cfg.get("embedding") or {"provider": "fake"}
            handle = VectorStoreHandle(connection=connection, collection=str(collection))

            query = str(
                ctx.get_input(state, "query")  # connected TEXT port wins over typed value
                or last_message_text(state, human_only=True)
                or last_message_text(state)
            )
            emb = _embeddings(embedding_cfg)
            vector = list(await emb.aembed_query(query))
            provider = await _provider(handle, settings)
            flt = ctx.get_field("filter") or None
            raw_filter = ctx.get_field("raw_filter") or None
            threshold = ctx.get_field("score_threshold")
            try:
                docs = await provider.query(
                    handle.collection or "default",
                    vector,
                    k=int(ctx.get_field("k") or 4),
                    filter=flt,
                    score_threshold=float(threshold) if threshold is not None else None,
                    raw_filter=raw_filter,
                )
            except Exception as exc:
                from langgraph_agent_builder.schema.diagnostics import (
                    RuntimeError_,
                    RuntimeErrorCode,
                )

                raise RuntimeError_(RuntimeErrorCode.RT107, str(exc), node_id=ctx.node_id) from exc
            rc.emit(
                "retriever.hits",
                {"count": len(docs), "query": query[:200], "collection": handle.collection},
            )
            return {"documents": docs}

        return node
