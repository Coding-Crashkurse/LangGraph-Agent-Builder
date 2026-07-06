# 03 · rag_pgvector — requires: [openai, postgres]

`start → pgvector Retriever → Prompt Template ({context}/{question} ports) → LLM Call → end`.

**Shows:** RAG over pgvector, dynamic `{var}` prompt ports, deep validate (E901
on the SQLite tier — the retriever demands Postgres).

```bash
docker compose up -d postgres
export LGA_DATABASE_URL=postgresql+asyncpg://graphforge:graphforge@localhost:55432/graphforge
export LGA_CRED_OPENAI_API_KEY=sk-…
python examples/03_rag_pgvector/seed.py
lga flow import examples/03_rag_pgvector/flow.json && lga flow publish library-rag
lga flow run library-rag --input "Who wrote The Left Hand of Darkness?"
# → …Ursula K. Le Guin…
```
