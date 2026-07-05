"""Ingestion helpers for pgvector collections (endpoint + CLI use the same code).

pgvector tables are owned by langchain-postgres — never alembic-managed
(CLAUDE.md §11)."""

import logging
from functools import lru_cache
from pathlib import Path

from langchain.embeddings import init_embeddings
from langchain_core.documents import Document
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter

from graphforge.settings import Settings

logger = logging.getLogger(__name__)

INGESTABLE_SUFFIXES = {".txt", ".md", ".markdown", ".rst"}


@lru_cache(maxsize=32)
def _cached_store(database_url: str, embedding_model: str, collection: str) -> PGVector:
    return PGVector(
        embeddings=init_embeddings(embedding_model),
        collection_name=collection,
        connection=database_url,
        use_jsonb=True,
        async_mode=True,
    )


def get_vector_store(settings: Settings, collection: str) -> PGVector:
    return _cached_store(settings.database_url, settings.embedding_model, collection)


def chunk_text(text: str, *, source: str = "") -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    metadata = {"source": source} if source else {}
    return [
        Document(page_content=chunk, metadata=dict(metadata))
        for chunk in splitter.split_text(text)
        if chunk.strip()
    ]


async def ingest_text(settings: Settings, collection: str, text: str, *, source: str = "") -> int:
    documents = chunk_text(text, source=source)
    if not documents:
        return 0
    store = get_vector_store(settings, collection)
    await store.aadd_documents(documents)
    return len(documents)


def _collect_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*") if p.suffix.lower() in INGESTABLE_SUFFIXES and p.is_file()
        )
    return [path]


async def ingest_path(settings: Settings, collection: str, path: Path) -> dict[str, int]:
    """Ingest a file or directory (txt/md); returns {file: chunk_count}."""
    import asyncio

    files = await asyncio.to_thread(_collect_files, path)
    results: dict[str, int] = {}
    for file in files:
        text = await asyncio.to_thread(file.read_text, encoding="utf-8", errors="replace")
        count = await ingest_text(settings, collection, text, source=file.name)
        results[str(file)] = count
        logger.info("ingested %s: %d chunks", file, count)
    return results
