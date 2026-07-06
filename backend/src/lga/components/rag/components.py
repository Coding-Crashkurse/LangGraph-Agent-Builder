"""RAG catalog (SPEC §12.4): retriever, embeddings, splitter, loader, writer."""

from __future__ import annotations

from typing import Any

from lga.sdk import Component, Output, fields, ports
from lga.sdk.ports import Document
from lga.sdk.runtime import get_run_context
from lga.sdk.templating import last_message_text


class PgvectorRetriever(Component):
    component_id = "lga.rag.pgvector_retriever"
    display_name = "pgvector Retriever"
    description = "Similarity search over a pgvector collection → Documents."
    icon = "database-zap"
    category = "rag"

    inputs = [
        fields.DropdownInput(
            name="collection",
            display_name="Collection",
            required=True,
            options_source="pgvector_collections",
            combobox=True,
        ),
        fields.IntInput(name="k", display_name="Top K", default=4, min=1, max=50),
        fields.ModelInput(
            name="embeddings",
            display_name="Embeddings",
            info="Embedding provider; must match the one used at ingestion.",
        ),
        fields.NestedDictInput(name="filter", display_name="Metadata Filter", advanced=True),
        fields.FloatInput(
            name="score_threshold",
            display_name="Score Threshold",
            advanced=True,
            min=0.0,
            max=1.0,
        ),
        fields.HandleField(name="query", display_name="Query", as_port=ports.TEXT),
    ]
    outputs = [Output(name="documents", display_name="Documents", port=ports.DOCUMENTS)]

    def build(self, ctx):
        settings = ctx.settings

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            from lga.components.rag._store import get_vector_store

            rc = get_run_context(config)
            query = str(
                ctx.get_input(state, "query")
                or last_message_text(state, human_only=True)
                or last_message_text(state)
            )
            store = get_vector_store(
                settings, str(ctx.get_field("collection")), ctx.get_field("embeddings")
            )
            kwargs: dict[str, Any] = {"k": int(ctx.get_field("k") or 4)}
            if ctx.get_field("filter"):
                kwargs["filter"] = ctx.get_field("filter")
            results = await store.asimilarity_search_with_relevance_scores(query, **kwargs)
            threshold = ctx.get_field("score_threshold")
            documents = [
                Document(page_content=d.page_content, metadata=dict(d.metadata or {}), score=s)
                for d, s in results
                if threshold is None or s >= float(threshold)
            ]
            rc.emit(
                "retriever.hits",
                {
                    "count": len(documents),
                    "query": query[:200],
                    "sources": [d.metadata.get("source", "") for d in documents],
                },
            )
            return {"documents": documents}

        return node

    async def health_check(self, ctx) -> None:
        from lga.components.rag._store import get_vector_store

        get_vector_store(
            ctx.settings,
            str(ctx.get_field("collection") or "healthcheck"),
            ctx.get_field("embeddings"),
        )


class Embeddings(Component):
    component_id = "lga.rag.embeddings"
    display_name = "Embeddings"
    description = "Embedding model handle for retrievers/writers."
    icon = "binary"
    category = "rag"

    inputs = [fields.ModelInput(name="model", display_name="Model", required=True)]
    outputs = [Output(name="embedding", display_name="Embedding", port=ports.EMBEDDING)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            from lga.components.llm._models import resolve_embeddings

            return {"embedding": resolve_embeddings(ctx.get_field("model"))}

        return node


class TextSplitter(Component):
    component_id = "lga.rag.text_splitter"
    display_name = "Text Splitter"
    description = "Recursive character splitting: Text/Documents → Documents."
    icon = "scissors-line-dashed"
    category = "rag"

    inputs = [
        fields.IntInput(
            name="chunk_size", display_name="Chunk Size", default=800, min=50, max=8000
        ),
        fields.IntInput(name="chunk_overlap", display_name="Overlap", default=120, min=0, max=2000),
        fields.HandleField(name="text", display_name="Text", as_port=ports.TEXT),
        fields.HandleField(name="documents", display_name="Documents", as_port=ports.DOCUMENTS),
    ]
    outputs = [Output(name="documents", display_name="Documents", port=ports.DOCUMENTS)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            try:
                from langchain_text_splitters import RecursiveCharacterTextSplitter
            except ImportError as exc:
                raise RuntimeError("text splitting requires: uv add 'lga[pgvector]'") from exc

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=int(ctx.get_field("chunk_size") or 800),
                chunk_overlap=int(ctx.get_field("chunk_overlap") or 120),
            )
            docs_in = ctx.get_input(state, "documents") or []
            text_in = ctx.get_input(state, "text")
            documents: list[Document] = []
            if text_in:
                for chunk in splitter.split_text(str(text_in)):
                    documents.append(Document(page_content=chunk, metadata={}))
            for doc in docs_in:
                content = doc.page_content if isinstance(doc, Document) else str(doc)
                meta = dict(doc.metadata) if isinstance(doc, Document) else {}
                for chunk in splitter.split_text(content):
                    documents.append(Document(page_content=chunk, metadata=meta))
            return {"documents": documents}

        return node


class FileLoader(Component):
    component_id = "lga.rag.file_loader"
    display_name = "File Loader"
    description = "Load uploaded files (txt/md/pdf) into Documents."
    icon = "file-input"
    category = "rag"

    inputs = [
        fields.FileInput(
            name="files",
            display_name="Files",
            file_types=[".txt", ".md", ".pdf"],
            multiple=True,
        ),
        fields.HandleField(name="file_refs", display_name="Files", as_port=ports.FILE_REF),
    ]
    outputs = [Output(name="documents", display_name="Documents", port=ports.DOCUMENTS)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            from lga.services.locator import require_services

            svc = require_services("file_loader")
            file_ids: list[str] = list(ctx.get_field("files") or [])
            refs = ctx.get_input(state, "file_refs") or []
            for ref in refs if isinstance(refs, list) else [refs]:
                fid = ref.get("file_id") if isinstance(ref, dict) else getattr(ref, "file_id", "")
                if fid:
                    file_ids.append(fid)
            documents: list[Document] = []
            for file_id in file_ids:
                found = await svc.files.get(file_id)
                if found is None:
                    continue
                row, content = found
                if row.mime == "application/pdf" or row.name.lower().endswith(".pdf"):
                    import io

                    from pypdf import PdfReader

                    reader = PdfReader(io.BytesIO(content))
                    text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
                else:
                    text = content.decode("utf-8", errors="replace")
                documents.append(
                    Document(page_content=text, metadata={"source": row.name, "file_id": row.id})
                )
            return {"documents": documents}

        return node


class PgvectorWriter(Component):
    component_id = "lga.rag.pgvector_writer"
    display_name = "pgvector Writer"
    description = "Write Documents into a pgvector collection (used by seed flows)."
    icon = "database"
    category = "rag"

    inputs = [
        fields.StrInput(name="collection", display_name="Collection", required=True),
        fields.ModelInput(name="embeddings", display_name="Embeddings"),
        fields.HandleField(name="documents", display_name="Documents", as_port=ports.DOCUMENTS),
    ]
    outputs = [Output(name="json", display_name="Result", port=ports.JSON)]

    def build(self, ctx):
        settings = ctx.settings

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            from langchain_core.documents import Document as LCDocument

            from lga.components.rag._store import get_vector_store

            docs = ctx.get_input(state, "documents") or []
            store = get_vector_store(
                settings, str(ctx.get_field("collection")), ctx.get_field("embeddings")
            )
            lc_docs = [
                LCDocument(
                    page_content=d.page_content if isinstance(d, Document) else str(d),
                    metadata=dict(d.metadata) if isinstance(d, Document) else {},
                )
                for d in docs
            ]
            ids = await store.aadd_documents(lc_docs)
            return {
                "json": {"written": len(ids), "collection": ctx.get_field("collection")},
                "data": {"ingested": len(ids)},
            }

        return node
