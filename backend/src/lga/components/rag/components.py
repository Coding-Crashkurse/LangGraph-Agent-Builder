"""RAG catalog (SPEC §12.4) — backend-agnostic vector store abstraction (§8b).

Retriever/Writer take a named Vector Store Connection (``VectorStoreInput``) plus
an ``Embedding`` port. The legacy pgvector nodes remain loadable but are hidden
from the sidebar and point at their successors (§8b.4, §4.11).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from lga.sdk import Component, Output, fields, ports
from lga.sdk.component import BuildContext, NodeConfig, NodeFn
from lga.sdk.ports import Document, VectorStoreHandle
from lga.sdk.runtime import get_run_context
from lga.sdk.templating import last_message_text

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings as LangchainEmbeddings

    from lga.vectorstores.base import VectorStoreProvider


# --------------------------------------------------------------------------- helpers
def _handle(value: Any) -> VectorStoreHandle:
    if isinstance(value, VectorStoreHandle):
        return value
    if isinstance(value, dict):
        return VectorStoreHandle(
            connection=str(value.get("$vectorstore") or value.get("connection") or "local"),
            collection=value.get("collection"),
        )
    return VectorStoreHandle(connection="local")


async def _provider(handle: VectorStoreHandle, settings: Any) -> VectorStoreProvider:
    """Resolve a live provider for a connection — via services when the server
    is up, else a direct ``local`` provider (headless / ``--local`` runs)."""
    try:
        from lga.services.locator import get_services

        svc = get_services()
    except Exception:
        svc = None
    if svc is not None and getattr(svc, "vectorstores", None) is not None:
        return cast("VectorStoreProvider", await svc.vectorstores.provider(handle.connection))
    from lga.services.settings import get_settings
    from lga.vectorstores import build_provider

    st = settings or get_settings()
    return build_provider("local", handle.connection, {}, home=st.home)


def _embeddings(value: Any) -> LangchainEmbeddings:
    from lga.components.llm._models import resolve_embeddings

    return resolve_embeddings(value or {"provider": "fake"})


def _as_document(d: Any) -> Document:
    if isinstance(d, Document):
        return d
    if isinstance(d, dict):
        return Document(
            page_content=str(d.get("page_content", "")),
            metadata=dict(d.get("metadata") or {}),
        )
    return Document(page_content=str(d))


# --------------------------------------------------------------------------- retriever
class VectorRetriever(Component):
    component_id = "lga.rag.retriever"
    display_name = "Vector Retriever"
    description = "Similarity search over a Vector Store Connection → Documents."
    icon = "search"
    category = "rag"
    priority: ClassVar[int | None] = 10
    tool_mode_supported = True

    inputs = [
        fields.VectorStoreInput(
            name="vector_store",
            display_name="Vector Store",
            required=True,
            options_source="vectorstore_collections",
        ),
        fields.IntInput(name="k", display_name="Top K", default=4, min=1, max=50),
        fields.QueryInput(name="query", display_name="Query", tool_mode=True),
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
        fields.HandleField(name="embedding", display_name="Embedding", as_port=ports.EMBEDDING),
        fields.HandleField(
            name="query_port", display_name="Query (from upstream)", as_port=ports.TEXT
        ),
    ]
    outputs = [Output(name="documents", display_name="Documents", port=ports.DOCUMENTS)]

    def build(self, ctx: BuildContext) -> NodeFn:
        settings = ctx.settings

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            handle = _handle(ctx.get_field("vector_store"))
            query = str(
                ctx.get_input(state, "query_port")
                or ctx.get_field("query")
                or last_message_text(state, human_only=True)
                or last_message_text(state)
            )
            embedding_cfg = ctx.get_input(state, "embedding") or {"provider": "fake"}
            emb = _embeddings(embedding_cfg)
            vector = list(await emb.aembed_query(query))
            provider = await _provider(handle, settings)
            flt = ctx.get_field("filter") or ctx.get_field("raw_filter") or None
            threshold = ctx.get_field("score_threshold")
            try:
                docs = await provider.query(
                    handle.collection or "default",
                    vector,
                    k=int(ctx.get_field("k") or 4),
                    filter=flt,
                    score_threshold=float(threshold) if threshold is not None else None,
                )
            except Exception as exc:
                from lga.schema.diagnostics import RuntimeError_, RuntimeErrorCode

                raise RuntimeError_(RuntimeErrorCode.RT107, str(exc), node_id=ctx.node_id) from exc
            rc.emit(
                "retriever.hits",
                {"count": len(docs), "query": query[:200], "collection": handle.collection},
            )
            return {"documents": docs}

        return node

    async def health_check(self, ctx: BuildContext) -> None:
        handle = _handle(ctx.get_field("vector_store"))
        provider = await _provider(handle, ctx.settings)
        await provider.health()


# --------------------------------------------------------------------------- writer
class VectorWriter(Component):
    component_id = "lga.rag.writer"
    display_name = "Vector Writer"
    description = "Embed Documents and upsert into a Vector Store collection."
    icon = "database"
    category = "rag"
    priority: ClassVar[int | None] = 20

    inputs = [
        fields.VectorStoreInput(
            name="vector_store",
            display_name="Vector Store",
            required=True,
            allow_create_collection=True,
            options_source="vectorstore_collections",
        ),
        fields.HandleField(name="embedding", display_name="Embedding", as_port=ports.EMBEDDING),
        fields.HandleField(name="documents", display_name="Documents", as_port=ports.DOCUMENTS),
    ]
    outputs = [Output(name="json", display_name="Result", port=ports.JSON)]

    def build(self, ctx: BuildContext) -> NodeFn:
        settings = ctx.settings

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            handle = _handle(ctx.get_field("vector_store"))
            collection = handle.collection or "default"
            docs = [_as_document(d) for d in (ctx.get_input(state, "documents") or [])]
            embedding_cfg = ctx.get_input(state, "embedding") or {"provider": "fake"}
            emb = _embeddings(embedding_cfg)
            vectors = [list(v) for v in await emb.aembed_documents([d.page_content for d in docs])]
            dim = len(vectors[0]) if vectors else int((embedding_cfg or {}).get("dim") or 32)
            provider = await _provider(handle, settings)
            try:
                await provider.ensure_collection(collection, dim)
                result = await provider.upsert(collection, docs, vectors)
            except Exception as exc:
                from lga.schema.diagnostics import RuntimeError_, RuntimeErrorCode

                raise RuntimeError_(RuntimeErrorCode.RT107, str(exc), node_id=ctx.node_id) from exc
            return {
                "json": {"written": result.count, "collection": collection},
                # also expose the count on the shared `data` channel (merge_data, §5.1)
                "data": {"ingested": result.count},
            }

        return node


# --------------------------------------------------------------------------- embeddings
class Embeddings(Component):
    component_id = "lga.rag.embeddings"
    display_name = "Embeddings"
    description = "Embedding model handle for retrievers/writers."
    icon = "binary"
    category = "rag"
    priority = 30

    inputs = [
        fields.EmbeddingModelInput(name="model", display_name="Model", required=True),
    ]
    outputs = [Output(name="embedding", display_name="Embedding", port=ports.EMBEDDING)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            from lga.components.llm._models import parse_model_value

            # the EMBEDDING port carries serializable provider config — never a client
            return {"embedding": parse_model_value(ctx.get_field("model") or {"provider": "fake"})}

        return node


# --------------------------------------------------------------------------- text splitter
class TextSplitter(Component):
    component_id = "lga.rag.text_splitter"
    display_name = "Text Splitter"
    description = "Recursive character splitting: Text/Documents → Documents."
    icon = "scissors-line-dashed"
    category = "rag"
    priority = 40

    inputs = [
        fields.IntInput(
            name="chunk_size", display_name="Chunk Size", default=800, min=50, max=8000
        ),
        fields.IntInput(name="chunk_overlap", display_name="Overlap", default=120, min=0, max=2000),
        fields.HandleField(name="text", display_name="Text", as_port=ports.TEXT),
        fields.HandleField(name="documents", display_name="Documents", as_port=ports.DOCUMENTS),
    ]
    outputs = [Output(name="documents", display_name="Documents", port=ports.DOCUMENTS)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            size = int(ctx.get_field("chunk_size") or 800)
            overlap = int(ctx.get_field("chunk_overlap") or 120)
            documents: list[Document] = []
            text_in = ctx.get_input(state, "text")
            if text_in:
                for chunk in _split(str(text_in), size, overlap):
                    documents.append(Document(page_content=chunk, metadata={}))
            for doc in ctx.get_input(state, "documents") or []:
                d = _as_document(doc)
                for chunk in _split(d.page_content, size, overlap):
                    documents.append(Document(page_content=chunk, metadata=dict(d.metadata)))
            return {"documents": documents}

        return node


def _split(text: str, size: int, overlap: int) -> list[str]:
    """Pure-Python recursive character split (no external dependency)."""
    text = text.strip()
    if not text:
        return []
    seps = ["\n\n", "\n", ". ", " "]

    def _rec(chunk: str, seps: list[str]) -> list[str]:
        if len(chunk) <= size:
            return [chunk]
        if not seps:
            # guard: overlap >= size would make the step 0/negative (ValueError) or
            # drop chunks silently — never let the stride fall below 1
            step = max(1, size - overlap)
            return [chunk[i : i + size] for i in range(0, len(chunk), step)]
        sep = seps[0]
        parts = chunk.split(sep)
        out: list[str] = []
        buf = ""
        for part in parts:
            candidate = (buf + sep + part) if buf else part
            if len(candidate) <= size:
                buf = candidate
            else:
                if buf:
                    out.extend(_rec(buf, seps[1:]))
                buf = part
        if buf:
            out.extend(_rec(buf, seps[1:]))
        return out

    return [c for c in _rec(text, seps) if c.strip()]


# --------------------------------------------------------------------------- file loader
class FileLoader(Component):
    component_id = "lga.rag.file_loader"
    display_name = "File Loader"
    description = "Load uploaded files (txt/md/pdf/csv/json) into Documents."
    icon = "file-input"
    category = "rag"
    priority = 50

    inputs = [
        fields.FileInput(
            name="files",
            display_name="Files",
            file_types=[".txt", ".md", ".pdf", ".csv", ".json"],
            multiple=True,
        ),
        fields.HandleField(
            name="file_refs", display_name="File Refs (from upstream)", as_port=ports.FILE_REF
        ),
    ]
    outputs = [Output(name="documents", display_name="Documents", port=ports.DOCUMENTS)]

    def build(self, ctx: BuildContext) -> NodeFn:
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
                documents.extend(_load_file(row.name, row.mime, content))
            return {"documents": documents}

        return node


def _load_file(name: str, mime: str, content: bytes) -> list[Document]:
    lower = name.lower()
    if mime == "application/pdf" or lower.endswith(".pdf"):
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return [Document(page_content=text, metadata={"source": name})]
    text = content.decode("utf-8", errors="replace")
    if lower.endswith(".csv"):
        import csv
        import io

        rows = list(csv.DictReader(io.StringIO(text)))
        return [
            Document(
                page_content="\n".join(f"{k}: {v}" for k, v in row.items()),
                metadata={"source": name, "row": i},
            )
            for i, row in enumerate(rows)
        ]
    if lower.endswith(".json"):
        import json

        data = json.loads(text)
        items = data if isinstance(data, list) else [data]
        return [
            Document(page_content=str(item), metadata={"source": name, "index": i})
            for i, item in enumerate(items)
        ]
    return [Document(page_content=text, metadata={"source": name})]


# --------------------------------------------------------------------------- legacy (§8b.4)
class PgvectorRetriever(VectorRetriever):
    component_id = "lga.rag.pgvector_retriever"
    display_name = "pgvector Retriever"
    description = "Legacy pgvector retriever — replaced by Vector Retriever (§8b.4)."
    legacy = True
    successor = "lga.rag.retriever"
    priority: ClassVar[int | None] = None

    inputs = [
        fields.DropdownInput(
            name="collection",
            display_name="Collection",
            required=True,
            combobox=True,
        ),
        fields.IntInput(name="k", display_name="Top K", default=4, min=1, max=50),
        # inherited build() reads the "embedding" port (singular) + an Embedding
        # value — not an LLM ModelInput; match the non-legacy VectorRetriever.
        fields.EmbeddingModelInput(
            name="embedding", display_name="Embeddings", as_port=ports.EMBEDDING
        ),
        fields.NestedDictInput(name="filter", display_name="Metadata Filter", advanced=True),
        fields.FloatInput(
            name="score_threshold", display_name="Score Threshold", advanced=True, min=0.0, max=1.0
        ),
        fields.HandleField(name="query", display_name="Query", as_port=ports.TEXT),
    ]

    @classmethod
    def migrate_config(cls, old_version: str, config: NodeConfig) -> NodeConfig:
        """Map the legacy shape onto the new Vector Retriever config."""
        cfg = dict(config)
        collection = cfg.pop("collection", None)
        cfg["vector_store"] = {"$vectorstore": "local", "collection": collection}
        return cfg


class PgvectorWriter(VectorWriter):
    component_id = "lga.rag.pgvector_writer"
    display_name = "pgvector Writer"
    description = "Legacy pgvector writer — replaced by Vector Writer (§8b.4)."
    legacy = True
    successor = "lga.rag.writer"
    priority: ClassVar[int | None] = None

    inputs = [
        fields.StrInput(name="collection", display_name="Collection", required=True),
        fields.EmbeddingModelInput(
            name="embedding", display_name="Embeddings", as_port=ports.EMBEDDING
        ),
        fields.HandleField(name="documents", display_name="Documents", as_port=ports.DOCUMENTS),
    ]

    @classmethod
    def migrate_config(cls, old_version: str, config: NodeConfig) -> NodeConfig:
        cfg = dict(config)
        collection = cfg.pop("collection", None)
        cfg["vector_store"] = {"$vectorstore": "local", "collection": collection}
        return cfg
