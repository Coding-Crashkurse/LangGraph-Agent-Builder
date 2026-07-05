"""RAG collections: list + ingest (text or file upload). CLAUDE.md §6.3/§13."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from graphforge.api.deps import SessionmakerDep, SettingsDep
from graphforge.rag.ingest import ingest_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collections", tags=["collections"])


class IngestTextRequest(BaseModel):
    text: str = Field(min_length=1)
    source: str = ""


@router.get("")
async def list_collections(sessionmaker: SessionmakerDep) -> list[dict[str, Any]]:
    query = text(
        """
        SELECT c.name AS name, count(e.id) AS documents
        FROM langchain_pg_collection c
        LEFT JOIN langchain_pg_embedding e ON e.collection_id = c.uuid
        GROUP BY c.name
        ORDER BY c.name
        """
    )
    try:
        async with sessionmaker() as session:
            rows = (await session.execute(query)).mappings().all()
        return [dict(row) for row in rows]
    except Exception:
        # pgvector tables are created lazily by langchain-postgres on first ingest
        return []


@router.post("/{name}/documents")
async def ingest_document_text(
    name: str, body: IngestTextRequest, settings: SettingsDep
) -> dict[str, Any]:
    chunks = await ingest_text(settings, name, body.text, source=body.source)
    return {"collection": name, "chunks": chunks}


@router.post("/{name}/files")
async def ingest_document_file(
    name: str, settings: SettingsDep, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=415, detail="only utf-8 text files (txt/md) in the PoC"
        ) from exc
    chunks = await ingest_text(settings, name, content, source=file.filename or "upload")
    return {"collection": name, "chunks": chunks, "file": file.filename}
