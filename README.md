# GraphForge

Visual builder for **LangGraph** agent workflows. Compose flows on a React-Flow canvas,
publish them as **A2A servers** (JSON-RPC + REST) and/or **MCP servers** (streamable HTTP),
and watch every run live in a debug dashboard — tasks, SSE event tail, human-in-the-loop
input, graph replay.

> Architecture & conventions: **[CLAUDE.md](CLAUDE.md)** is the single source of truth.

## Quickstart

```bash
docker compose up -d postgres          # pgvector/pgvector:pg17 → host port 55432

# backend (Python ≥3.12, uv)
cd backend
cp .env.example .env                   # set OPENAI_API_KEY for real LLM/RAG flows
uv sync
uv run graphforge serve --reload       # http://localhost:8010 on this machine (see .env BASE_URL)

# frontend (Node ≥20, pnpm)
cd frontend
pnpm install
pnpm dev                               # http://localhost:5173, proxies /api + /serve
```

`uv run graphforge serve` is the blessed backend entry point — on Windows it arranges the
selector event loop psycopg async needs (bare non-reload `uvicorn` won't). Consequence of
that loop: `stdio` MCP toolsets are unavailable on Windows; use `streamable_http`.

Non-default ports on this dev box (both env-driven, not hardcoded):
- Postgres → **55432** (5432 is taken by another project)
- Backend → **8010** (8000 is taken) — set via `backend/.env` `BASE_URL` + `serve --port`

## What works end-to-end

- Flow CRUD, compiler validation with node/edge-level issues, publish/unpublish with
  dynamic mounting under `/serve/a2a/{slug}`, `/serve/rest/{slug}`, `/serve/mcp/{slug}`
- A2A: agent card at `…/.well-known/agent-card.json`, `message/send`, `message/stream`
  with custom progress events, multi-turn contexts (`contextId == thread_id`),
  `input-required` interrupts + resume, `tasks/cancel`
- MCP: one tool per flow (`(message, thread_id?) → str`), progress notifications,
  agent-card resource, HITL fails fast pointing to A2A (elicitation behind
  `ENABLE_MCP_ELICITATION`)
- Debug UI: live task list (SSE firehose), event tail with replay (`Last-Event-ID`),
  conversation + artifacts, mini graph replay, approve/reject & free-text input panels,
  playground (stream/send toggle)
- RAG: `POST /api/collections/{name}/documents` + `uv run graphforge ingest <collection> <path>`
  (needs an embedding provider key)

## Demo

The seeded **Library RAG Agent** flow (`examples/flows/library_rag.json`, also in the DB)
implements the CLAUDE.md §16 demo: retriever → agent (⟵ MCP toolset) → human approval,
with cycle on rejection. To run it for real: set `OPENAI_API_KEY`, ingest documents into
`library-docs`, point the `mcp_toolset` node at a reachable MCP server (or delete that
node), then publish from the builder.

For a keyless tour, start the backend with `TESTING=true` and build a flow from
`fake_llm` + `human_approval` — the whole HITL/streaming path works without any provider.

## Quality gates

```bash
cd backend  && uv run ruff check --fix && uv run ruff format && uv run pytest   # 36 tests
cd frontend && pnpm lint && pnpm test && pnpm build                             # 11 tests
```
