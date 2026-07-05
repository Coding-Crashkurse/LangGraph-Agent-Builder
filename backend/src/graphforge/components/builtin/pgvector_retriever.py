"""pgvector similarity retriever; writes state['documents']."""

from typing import Any

from pydantic import Field

from graphforge.components.base import BaseComponent, BuildContext, ComponentConfig, NodeFn
from graphforge.components.registry import register
from graphforge.components.templating import last_message_text, resolve_path
from graphforge.runtime.events import emit


class PGVectorRetrieverConfig(ComponentConfig):
    collection: str = Field(description="pgvector collection name (see /api/collections).")
    top_k: int = Field(4, ge=1, le=50)
    query_from: str = Field(
        "",
        description=(
            "Optional state path for the query (e.g. 'data.query'); default: last human message."
        ),
    )


@register
class PGVectorRetriever(BaseComponent):
    name = "pgvector_retriever"
    display_name = "pgvector Retriever"
    description = "Similarity search over a pgvector collection; writes documents."
    category = "rag"
    version = 1
    config_model = PGVectorRetrieverConfig
    state_reads = ["messages", "data"]
    state_writes = ["documents"]

    def build(self, config: PGVectorRetrieverConfig, ctx: BuildContext) -> NodeFn:
        settings = ctx.settings

        async def node(state: dict[str, Any], _config: Any) -> dict[str, Any]:
            from graphforge.rag.ingest import get_vector_store

            if config.query_from:
                query = str(resolve_path(state, config.query_from))
            else:
                query = last_message_text(state, human_only=True) or last_message_text(state)
            store = get_vector_store(settings, config.collection)
            documents = await store.asimilarity_search(query, k=config.top_k)
            emit(
                "retriever.hits",
                {
                    "count": len(documents),
                    "query": query[:200],
                    "sources": [(doc.metadata or {}).get("source", "") for doc in documents],
                },
            )
            return {"documents": documents}

        return node
