"""pgvector store access (extra: lga[pgvector]); Postgres tier only (E901)."""

from __future__ import annotations

from typing import Any


def get_vector_store(settings: Any, collection: str, embedding_value: Any = None):
    try:
        from langchain_postgres import PGVector
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pgvector support requires: uv add 'lga[pgvector]'") from exc
    if settings is None or not getattr(settings, "is_postgres", False):
        raise RuntimeError("pgvector requires the Postgres storage tier (E901)")
    from lga.components.llm._models import resolve_embeddings

    embeddings = resolve_embeddings(embedding_value or {"provider": "openai", "model": ""})
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    return PGVector(
        embeddings=embeddings,
        collection_name=collection,
        connection=dsn,
        use_jsonb=True,
        async_mode=True,
    )
