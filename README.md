# lga — LangGraph-native visual agent builder

Langflow-class UX, LangGraph-class engine (see `SPEC.md`, the authoritative
specification). Flows are composed on a typed react-flow canvas, **compiled**
to real LangGraph `StateGraph`s (all errors at validate time, never mid-run),
and every published flow is served as a spec-compliant **A2A agent** and/or
**MCP tool** — including human-in-the-loop interrupts that surface as A2A
`input-required` round trips.

```bash
uv tool install lga        # or: pip install lga
lga run                    # zero config: SQLite under ~/.lga, browser opens
```

## Highlights

- **Compile-time > runtime** — ports are Pydantic schemas; edges validate
  structurally (E020 names both schema_refs); diagnostics have stable codes.
- **A2A** (`/a2a/{slug}`, JSON-RPC 0.3.x): agent card on both well-known paths,
  streaming with token artifacts, tasks/cancel/resubscribe (store-backed
  replay), push notifications with SSRF guards, API-key auth or public with
  per-client session namespacing. Human Approval on the canvas ⇒
  `input-required` over the protocol ⇒ resume ⇒ `completed`.
- **MCP** (`/mcp`, streamable HTTP + `/mcp/sse` fallback): published flows are
  tools; client config snippet at `GET /api/v1/mcp/config`.
- **Component SDK** — one Python class per component, discovered via the
  `lga.components` entry point or `LGA_COMPONENTS_PATH`; no string-eval, ever.
  Scaffold with `lga component new`.
- **Library use** — `from lga.compiler import compile_flow`;
  `compile_flow(spec).graph` runs under vanilla LangGraph without the server.
  Export any flow to a standalone `flow.py`.
- **Storage tiers** — SQLite by default, Postgres (`LGA_DATABASE_URL=
  postgresql+asyncpg://…`) for production + pgvector RAG.

## Repository layout

| Path | What |
|---|---|
| `SPEC.md` | the authoritative product/architecture spec |
| `backend/` | the `lga` package (SDK, compiler, runtime, A2A, MCP, Studio API, CLI) |
| `frontend/` | React Studio (bundled into the wheel at build time) |
| `examples/01…10` | runnable examples incl. A2A HITL client, multi-agent, MCP both ways |

## A2A endpoints per published agent

- Card: `GET /a2a/{slug}/.well-known/agent-card.json` (legacy `agent.json`
  alias served too; `GET /a2a/{slug}/` also returns the card). The root
  `/.well-known/agent-card.json` lists per-agent card URLs — in v1 there is no
  directory agent.
- RPC: `POST /a2a/{slug}/` (JSON-RPC 2.0; `message/stream` answers as SSE
  where each `data:` field is one complete JSON-RPC response).

## Development

```bash
docker compose up -d postgres            # optional: Postgres tier on :55432

cd backend
uv sync
uv run lga run --port 8010               # this dev box keeps 8000 occupied
uv run pytest                            # unit + compiler goldens + A2A compliance + MCP + CLI

cd ../frontend
pnpm install
pnpm dev                                 # Vite on :5173, proxies /api /a2a /mcp → :8010
pnpm gen:api                             # regenerate src/api/schema.gen.ts from openapi.json
```

Quality gates (run before every commit):

```bash
cd backend  && uv run ruff check --fix && uv run ruff format && uv run pytest
cd frontend && pnpm lint && pnpm test && pnpm build
cd backend  && uv run pytest ../examples          # the example matrix stays green
```

Windows note: start the backend via `lga run` (it installs a selector event
loop; psycopg async cannot run on the Proactor loop). Consequence: `stdio` MCP
toolsets are unavailable on Windows — use `streamable_http`.
