# 11 · rag_compose_no_keys — requires: [postgres] (NO API keys)

Real pgvector retrieval against a Docker-Compose Postgres, with **zero API
keys**: deterministic fake embeddings (`{"provider": "fake"}`) and the `echo`
model provider, which returns the rendered prompt — so the final answer shows
you *exactly* which documents were retrieved.

```
seed_flow.json:  start → Text Input (corpus) → Text Splitter → pgvector Writer → end
flow.json:       start → pgvector Retriever ┐
                   └────────────────────────┴→ LLM Call (echo) → end
```

**Shows:** ingestion-as-a-flow (dogfooding: no Python seed script), real
pgvector similarity search, `{context}`/`{question}` prompt ports with the
`Documents → Text` coercion, the `echo`/`fake` providers for key-free testing.

> Note: `fake` embeddings are deterministic but have no semantics — the
> *ranking* is arbitrary (bump `k` to see all docs). Swap in real embeddings
> for meaningful similarity; the wiring stays identical.

```bash
cd examples/11_rag_compose_no_keys
docker compose up -d --wait

export LAB_DATABASE_URL=postgresql+asyncpg://lab:lab@localhost:55432/lab
lab run --port 8010 &            # or run it in a second terminal

# ingest the mini-library (a flow, not a script)
lab flow import seed_flow.json flow.json
lab flow run seed-mini-library --input go
# → {"written": 3, "collection": "mini-library"}

lab flow publish rag-no-keys
lab flow run rag-no-keys --input "Who wrote The Left Hand of Darkness?"
# → Context:
# → The Left Hand of Darkness was written by Ursula K. Le Guin …
# → Question: Who wrote The Left Hand of Darkness?
```

Swap `{"provider": "echo"}` for `{"provider": "openai", "model": "gpt-4o-mini"}`
and store the key as a credential (Settings → Global Variables, or the 🔑 picker
on any secret field, or `LAB_CRED_OPENAI_API_KEY=…`) — the flow itself never
contains the key, only `{"$secret": "OPENAI_API_KEY"}`.
