# 13 · RAG on the local vector store (no keys, no server)

Demonstrates the **v2 vector-store abstraction** (SPEC §8b): the `local` backend
is auto-created on first boot, so retrieval-augmented flows run with **zero
configuration** — no Postgres, no Qdrant, no API keys.

## What it shows

- **`rag.writer`** embeds documents and upserts them into a named
  *Vector Store Connection* + collection (`{"$vectorstore": "local", "collection": "kb"}`).
- **`rag.retriever`** does similarity search over the same connection.
- Both default to deterministic **fake embeddings** (`testing.fake_embeddings`,
  dim 32) when no `Embedding` port is wired — so the example is fully offline.
- **Slug-first** run URLs (`/api/v1/flows/rag-local/run`).

## Run it

```bash
cd backend && uv run pytest ../examples/13_rag_local
```

The test seeds the `kb` collection with `seed_flow.json`, then runs `flow.json`
and asserts the retrieved chunk mentions "cosine".

## Swap the backend without touching the flow

Point the same FlowSpec at Qdrant by declaring a connection via env — the
`$vectorstore` name resolves to whatever backend the connection uses:

```bash
export LGA_VECTORSTORE_KB='{"backend":"qdrant","url":"http://localhost:6333"}'
# then reference {"$vectorstore":"kb", ...} instead of "local"
uv pip install "langgraph-agent-builder[qdrant]"
```
