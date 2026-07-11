"""Seed the `library-docs` pgvector collection. requires: [openai, postgres]

Usage:
    LAB_DATABASE_URL=postgresql+asyncpg://… OPENAI_API_KEY=sk-… python seed.py
"""

from __future__ import annotations

import asyncio
import sys

DOCS = [
    ("The Left Hand of Darkness was written by Ursula K. Le Guin in 1969.",
     {"source": "catalog/leguin.md"}),
    ("Dune, by Frank Herbert, won the first Nebula Award for Best Novel.",
     {"source": "catalog/herbert.md"}),
    ("The library opens Monday through Saturday from 9:00 to 20:00.",
     {"source": "handbook/hours.md"}),
    ("Members can borrow up to 12 physical items and 20 e-books at once.",
     {"source": "handbook/lending.md"}),
]


async def main() -> None:
    from langchain_core.documents import Document

    from langgraph_agent_builder.components.rag._store import get_vector_store
    from langgraph_agent_builder.services.settings import get_settings

    settings = get_settings()
    if not settings.is_postgres:
        sys.exit("seed.py requires LAB_DATABASE_URL pointing at Postgres (pgvector)")
    store = get_vector_store(
        settings, "library-docs", {"provider": "openai", "model": "text-embedding-3-small"}
    )
    ids = await store.aadd_documents(
        [Document(page_content=text, metadata=meta) for text, meta in DOCS]
    )
    print(f"seeded {len(ids)} documents into library-docs")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
