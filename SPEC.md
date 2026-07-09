# SPEC.md — LangGraph-A2A Visual Agent Builder · **v2.0** (2026-07-07)

> **Audience:** Claude Code. This document is the authoritative specification for the
> `LANGGRAPH_A2A` repository. When implementing, follow this spec over ad-hoc decisions.
> When the spec is ambiguous, prefer: (1) A2A protocol spec compliance, (2) LangGraph-native
> semantics, (3) Langflow UX conventions — in that order.
>
> **Repo layout (already exists):** `backend/`, `frontend/`, `examples/`, `docker-compose.yml`,
> `CLAUDE.md`, `README.md`, `SPEC.md` (this file).
>
> **Frontend status:** an exemplary React canvas exists (sidebar categories LLM / RAG /
> Flow Control / Tools / IO & Glue; nodes `start`, `end`, `Fake LLM (testing)`, `LLM Agent`,
> `LLM Call`, `pgvector Retriever`, `Human Approval`, `Human Input`, `LLM Router`,
> `MCP Toolset`, `Set Data`, `Slow Node (testing)`; toolbar `Validate | Save | Publish |
> Debug`; version badge; Flow Settings panel with VALIDATION section; dashed sky tool edges;
> amber router handles). The current node visuals are PoC-grade (heavy glow, unlabeled ports,
> ad-hoc spacing) — §11 replaces them with a proper design system. Functional conventions of
> the prototype must not regress.

---

## 0. How to read / use this spec

- Sections marked **[MUST]** are hard requirements (A2A compliance, type safety, security).
- Sections marked **[SHOULD]** are strong defaults; deviate only with a written note in `CLAUDE.md`.
- Sections marked **[LATER]** are explicitly out of scope for v1 milestones — stub interfaces, don't build.
- Every public behavior in this spec must be covered by a test (see §15).
- Identifiers, error codes, JSON field names in this spec are **normative** — copy them verbatim.

### 0.1 Changelog v1 → v2 (informative)

1. **Vector store abstraction (§4.3, §8b, §12.4):** the pgvector-only retriever is replaced
   by named **Vector Store Connections** with pluggable backends — `local` (sqlite-vec,
   zero-config, works on the SQLite tier), `pgvector`, `qdrant`, `weaviate`, `chroma` — each
   an optional extra. New port family `VECTORSTORE`, new diagnostics `E90x`.
2. **Design system (§11.1–11.4, Appendix C):** complete visual spec — self-hosted fonts,
   Tailwind v4 token system, node anatomy, port palette with shape encoding, state visuals,
   motion, accessibility. Replaces the PoC look shown in the current prototype.
3. **Langflow parity round 2 (§18, sourced from docs.langflow.org 2026-07):** per-node
   component version pinning + update notifications (§4.11), partial runs / "Run to node"
   (§6.4), background runs (§6.5), header-passed global variables (§9.4), env-var fallback,
   flow locking (§9.1), Message History component, Mock Data, Current Date, Web Search,
   template gallery, keyboard shortcuts (§11.9). Explicitly rejected: vertex `/build` API,
   folders/projects, store/marketplace, embedded chat widget, Python Interpreter.
4. **Slug-first API (§9):** every endpoint that takes `{id}` also accepts the flow `slug`
   (`{id_or_slug}`) — no UUID-only ergonomics anywhere a human types a URL.
5. **New core port `lga:Table`** (Langflow DataFrame parity) and testing components
   `testing.fake_embeddings`, `testing.mock_data`.

---

## 1. Product overview

### 1.1 What we are building

A **LangGraph-native visual agent builder** ("Langflow-class UX, LangGraph-class engine"):

1. **Visual flow editor** (exists as prototype) where developers compose agents from typed
   components on a react-flow canvas — restyled per the §11 design system.
2. **A compiler** that turns the canvas graph (FlowSpec JSON) into a real LangGraph
   `StateGraph`, with **all errors surfaced at compile/validate time**, not runtime.
3. **A runtime** with durable checkpointing (SQLite zero-config, Postgres in production),
   streaming events, cancellation, human-in-the-loop interrupts, debug/step execution,
   partial ("run to node") and background runs.
4. **A2A protocol server** [MUST]: every *published* flow is a spec-compliant A2A agent
   (agent card, message/send, message/stream, tasks/*, push notifications, input-required
   mapping to LangGraph interrupts).
5. **MCP server**: every published flow is also exposable as an MCP tool (streamable HTTP,
   SSE fallback), plus an **MCP client** component (`MCP Toolset`) to attach external MCP
   tools to agents.
6. **Component SDK**: a typed Python SDK (Langflow-inspired but stricter) so developers can
   ship custom components as real installed packages — no string-eval.
7. **A distributable library + CLI** [MUST]: the whole product ships as ONE Python package
   (`uv add lga` / `pip install lga`, frontend bundled as static assets in the wheel) with a
   `lga` CLI (`lga run --env-file .env --port 8000 …`) — Langflow-style "pip install and go".
   Zero-config local start (SQLite + local vector store) with a clean upgrade path to
   Postgres / external vector DBs. Details in §2.5–§2.8.

### 1.2 Why (diagnosis of Langflow, which we fix by design)

| Langflow failure mode | Root cause | Our fix |
|---|---|---|
| Edges connect but flow crashes at runtime | Port types are coarse buckets (Message/Data/DataFrame); "both are Data" ≠ structurally compatible | Ports are **Pydantic schemas**; edge validation is structural (§4.3) |
| Config errors surface mid-run | No compile pass | Mandatory `validate` → `compile` pipeline with diagnostic codes (§5) |
| Flows un-reviewable / un-diffable | JSON blob is the program | FlowSpec is a *declarative spec* compiled to a real `StateGraph`; deterministic compile; export-to-Python (§5.7) |
| Custom components via `eval()` of code strings | Dynamic code loading | Components are installed Python classes discovered via entry points / component dirs (§4.8) |
| Renaming a component class silently breaks all flows | Identity = class name (frontend tests the `type` attribute) | Stable `component_id` + semver + `legacy` flag; migration hooks (§4.9); per-node pinning with guided updates (§4.11) |
| DAG-only mindset; loops/HITL bolted on inside nodes | Bespoke vertex engine | LangGraph-native: cycles, conditional edges, `interrupt()`, checkpointing are first-class (§5.5, §6) |
| Huge dependency footprint (hundreds of bundled vendor components) | All integrations bundled into base | Slim core; integrations as optional extras with lazy imports (§2.3); one *generic* component per capability instead of one per vendor |
| Cryptic API: `/v1/run/$FLOW_ID`, vertex `/build` endpoints, verbose nested responses | Frontend-orchestration API reused as public API | Slug-first REST (§9), one `/run` + SSE event contract (§6.2); the frontend consumes the same public API |
| MCP bolted on; no A2A | Engine predates protocols | A2A + MCP contracts generated from the same typed flow IO schema (§7, §8) |
| Vector stores = per-vendor component zoo | LangChain wrapper per provider | One typed VectorStore abstraction + named connections; backends as extras (§8b) |

### 1.3 Target users

Developers building **PoCs and internal agents**. They can read Python; the canvas exists
for speed of composition, visibility of architecture, debugging, and demos — not to hide code.
The escape hatch to code must always be open (export to Python, custom components).

### 1.4 Non-goals (v1)

- No multi-tenant SaaS, orgs/teams/RBAC (single-user + API keys only). No projects/folders —
  flat flow list + tags + search.
- No Langflow-scale integration catalog (hundreds of vendor components). Catalog v1 is §12;
  vendor breadth arrives as separately installable component packages, never in core.
- No voice mode, no embedded chat widget, no marketplace/store, no shareable playground links.
- No gRPC / HTTP+REST A2A transports (JSON-RPC binding only; declare accordingly in agent card). [LATER]
- No visual subflow grouping UI (Flow-as-Component works via component, not canvas grouping). [LATER]
- No server-side execution of user-supplied Python (no Python Interpreter / REPL component —
  rejected by design, see §18.3). Custom logic ships as installed components.

### 1.5 Design principles [MUST]

1. **Compile-time > runtime.** Anything that can be rejected before execution, is.
2. **One typed source of truth.** Flow IO schema drives: node forms, edge validation,
   A2A agent card skills, MCP tool schemas, REST run payloads.
3. **LangGraph-native, not LangGraph-wrapped.** Components return plain LangGraph node
   functions; the compiled graph is a normal `StateGraph` usable without our runtime.
4. **Protocol fidelity.** A2A behavior follows the spec text, including error codes and
   SSE framing — verified by a compliance test suite (§15.3).
5. **Slim core.** `pip install lga` pulls FastAPI + LangGraph + Pydantic + a2a-sdk + mcp
   (+ sqlite-vec, see §8b.2) and nothing vendor-specific. Providers are extras:
   `lga[openai]`, `lga[anthropic]`, `lga[qdrant]`, `lga[weaviate]`, `lga[pgvector]`, `lga[chroma]`.
6. **Testing components are first-class** (`Fake LLM`, `Fake Embeddings`, `Slow Node`,
   `Failing Node`, `Mock Data`) so every example and CI run works without API keys.
7. **Humans type slugs, machines may use UUIDs.** Every public URL and CLI argument accepts
   the slug; UUIDs are an implementation detail.

---

## 2. Architecture

### 2.1 System diagram (logical)

```
frontend (react-flow canvas, exists)
   │  FlowSpec JSON  +  REST/SSE
   ▼
backend FastAPI app
   ├── /api/v1/...          Studio REST API (§9): flows CRUD, validate, run, events, secrets…
   ├── /a2a/{agent_slug}/   A2A JSON-RPC endpoint per published agent (§7)
   ├── /.well-known/...     agent cards (§7.3)
   └── /mcp/...             MCP server, streamable HTTP + SSE fallback (§8)
        │
        ▼
   compiler (FlowSpec → StateGraph)  ──►  runtime (LangGraph + Async{Sqlite,Postgres}Saver)
        │                                     │
   component registry (SDK, entry points)     ├── event bus → SSE / A2A stream / push
        │                                     └── app DB: checkpoints, tasks, flows,
   vector store connections (§8b)                  versions, secrets, api_keys, files
     local (sqlite-vec) | pgvector | qdrant | weaviate | chroma
```

### 2.2 Repo layout [SHOULD]

```
backend/
  pyproject.toml               # package name: lga  (extras: openai, anthropic, ollama,
                               #   pgvector, qdrant, weaviate, chroma, postgres, all, dev)
  src/lga/
    __init__.py
    sdk/                       # Component SDK (§4) — importable standalone
      component.py             # Component base class, NodeContext
      fields.py                # all *Input field classes (§4.2)
      ports.py                 # PortSpec, core port schemas (§4.3)
      outputs.py               # Output class
      registry.py              # discovery: entry points + component dirs
      testing.py               # ComponentTestHarness (§4.10)
    schema/
      flowspec.py              # FlowSpec pydantic models + JSON schema export (§5.2)
      state.py                 # FlowState definition (§5.1)
      events.py                # run event models (§6.2)
      diagnostics.py           # Diagnostic model + code enum (§5.4)
    compiler/
      parse.py, resolve.py, validate.py, wire.py, emit.py   # passes (§5.3)
      subgraph.py              # partial-run induced subgraphs (§6.4)
      export_python.py         # FlowSpec → standalone .py (§5.7)
    runtime/
      executor.py              # run orchestration, cancellation, debug/partial/background
      checkpoint.py            # CheckpointerFactory, thread mapping
      streams.py               # event fan-out (SSE, A2A, push)
    vectorstores/              # §8b
      base.py                  # VectorStoreProvider protocol + Collection API
      local.py                 # sqlite-vec backend (core)
      pgvector.py, qdrant.py, weaviate.py, chroma.py   # extras, lazy import
    a2a/                       # §7
      card.py, server.py, executor.py, tasks.py, push.py
    mcp/                       # §8
      server.py, client.py
    api/                       # §9 REST routers
      flows.py, runs.py, components.py, secrets.py, files.py, auth.py, webhook.py,
      vectorstores.py, templates.py
    services/
      secrets.py               # Fernet-encrypted global variables (§10.3)
      apikeys.py, files.py, db.py, settings.py
    components/                # built-in catalog v1 (§12), one module per component
      io/, llm/, flow_control/, rag/, tools/, data/, testing/
    cli/                       # §2.6 typer app
      main.py, run.py, init.py, flow.py, component.py, apikey.py, migrate.py
    _static/                   # built frontend, injected by hatch build hook (§2.5); gitignored
  hatch_build.py               # build hook: npm build → copy dist → _static
  tests/                       # §15
frontend/                      # exists; contracts in §11
examples/                      # §13
docker-compose.yml             # dev: postgres (pgvector image), qdrant (profile), backend
                               #   (--reload), frontend (vite)
```

### 2.3 Tech stack [MUST]

- Python ≥ 3.12, Pydantic v2, FastAPI + uvicorn, SQLModel/SQLAlchemy async, Alembic migrations.
- **LangGraph ≥ 1.x**; checkpointers: `langgraph-checkpoint-sqlite` (`AsyncSqliteSaver`,
  default) and `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`, production) — selected
  by database URL scheme (§2.8).
- **a2a-sdk** (official Python SDK) for A2A types + server plumbing; we own the executor.
- **mcp** Python SDK (FastMCP server, streamable HTTP transport).
- **typer** (+ rich) for the CLI; `python-dotenv` for `--env-file`/.env loading.
- LangChain-core only for message types + model interfaces (`BaseChatModel`, `Embeddings`);
  provider packages (`langchain-openai`, `langchain-anthropic`, …) are optional extras,
  lazily imported.
- **sqlite-vec** as core dependency (pure-wheel C extension, no server) powering the `local`
  vector store backend; vendor vector clients (`qdrant-client`, `weaviate-client`,
  `chromadb`, `pgvector`+asyncpg) are extras, lazily imported (§8b).
- Storage tiers per §2.8: SQLite (zero-config default) / Postgres 16 (+`pgvector` extension
  when that backend is chosen).
- Frontend: existing React + TypeScript + @xyflow/react + zustand; **Tailwind CSS v4** with
  the §11 token system; fonts self-hosted via `@fontsource` (§11.1); forms generated from
  component JSON schema (§11.5). **Built frontend ships inside the wheel** (§2.5).

### 2.4 Processes

Single backend process serves the bundled frontend (static), Studio API, A2A, and MCP
(different routers) — one `lga run` = the whole product. `docker-compose` remains the *dev*
setup (live frontend, Postgres, optional qdrant profile) and a production deployment option;
it is not required to use the product. No extra brokers. Long runs execute as asyncio tasks
in-process with cancellation tokens; multi-worker/horizontal scaling is [LATER] (uvicorn
`--workers` is accepted but only safe with Postgres; warn on SQLite).

### 2.5 Packaging & distribution [MUST]

- **One package, name `lga`** (placeholder — global-rename when final name is chosen),
  built with hatchling from `backend/pyproject.toml`.
- `[project.scripts] lga = "lga.cli.main:app"` → installs the `lga` command.
- **Frontend bundling:** a hatch build hook runs `npm ci && npm run build` in `../frontend`
  and copies `frontend/dist` into `lga/_static/` inside the wheel. Backend serves it at `/`
  (SPA fallback). The sdist/wheel must be installable **without** Node on the target machine.
  Fonts are bundled (self-hosted, §11.1) — the app must render correctly offline.
  `LGA_FRONTEND_PATH` env can point at an external build (dev override). CI builds the wheel
  and asserts `_static/index.html` exists.
- **Install paths (all must work, tested in CI §15.6):**
  - `uv tool install lga` → global CLI; `uvx lga run` → ephemeral run.
  - `uv add lga` / `pip install lga` → project dependency (embedding, §2.7).
  - `uv add "lga[openai,qdrant]"` — extras: `openai`, `anthropic`, `ollama`, `pgvector`,
    `qdrant`, `weaviate`, `chroma`, `postgres`, `all`, `dev`.
- **Versioning/release:** semver, single source in `lga/__init__.py.__version__`; tags
  `vX.Y.Z` trigger CI release: build wheel+sdist → `uv publish` to PyPI (Trusted Publishing),
  changelog from conventional commits. TestPyPI on release-candidate tags.
- Python 3.12–3.13 wheels (pure Python, `py3-none-any`).

### 2.6 CLI (`lga`) [MUST]

Typer app, `lga --help` polished (rich). **Config precedence [MUST]:**
CLI flag > process env > `--env-file FILE` > `./.env` (auto-loaded if present) > defaults.
Every flag maps 1:1 to an `LGA_*` env var (flag docs state the var name).

| Command | Flags / behavior |
|---|---|
| `lga run` (alias `lga start`) | Start the full server. `--host` (`LGA_HOST`, default `127.0.0.1`), `--port` (`LGA_PORT`, 8000; auto-increments if busy unless `--no-port-fallback`), `--env-file PATH`, `--database-url`, `--backend-only` (no static frontend), `--components-path` (repeatable), `--log-level`, `--workers N` (Postgres only, warn+force 1 on SQLite), `--reload` (dev), `--open/--no-open` (browser, default open when TTY), `--auto-migrate/--no-auto-migrate` (default on: run Alembic upgrade at boot). Prints a startup summary box: URL, DB backend, vector store backends available, auth on/off, served agents (A2A) & MCP endpoint. |
| `lga init [DIR]` | Scaffold a workspace: `.env` (commented template of §14), `components/` (with example component), `flows/`, `.gitignore`. `--force`. |
| `lga migrate` | Alembic upgrade head against resolved DB. `--revision`, `--sql` (offline). |
| `lga flow import PATH…` / `export ID_OR_SLUG [--format json\|python]` / `validate PATH [--deep]` / `publish ID_OR_SLUG [--bump patch]` / `run PATH_OR_ID_OR_SLUG [--input TEXT] [--data JSON] [--session ID] [--stream] [--until NODE]` | Headless flow ops against a running server (`--server URL`, `--api-key`; env `LGA_SERVER_URL`, `LGA_API_KEY`) **or** `--local` (in-process compile+run, no server — powers example 10 & CI). `validate` exits non-zero on ERROR diagnostics (CI-friendly, `--format json`). |
| `lga component new NAME [--category llm]` | Scaffold a custom component package (pyproject with entry point, class skeleton, harness test) into `--path` (default `./components`). |
| `lga apikey create --scopes … [--name]` / `list` / `revoke ID` | §10.4; works headless (direct DB) when server not running. |
| `lga config` | Print effective resolved config (secrets masked) + its source (flag/env/file/default) per key. |
| `lga version` | Package version, A2A protocolVersion, LangGraph version, DB backend, installed vector backends. |

Exit codes: 0 ok · 1 unexpected error · 2 usage error · 3 validation errors (`flow validate`)
· 4 connection/auth error. All commands support `--quiet` and `--json` where output exists.

### 2.7 Library / embedding API [MUST]

Public, semver-stable surface (everything else is private; enforced by
`lga/__init__.__all__` + API-surface snapshot test):

```python
from lga import create_app           # (settings: Settings | None) -> FastAPI  — mount or serve yourself
from lga import Settings            # pydantic-settings; mirrors §14 env vars
from lga.sdk import Component, Output, fields, ports, NodeContext   # component authoring (§4)
from lga.compiler import compile_flow    # (FlowSpec | dict | Path) -> CompiledFlow {graph, report, diagnostics}
from lga.runtime import run_flow, arun_flow   # headless execution (in-memory or given checkpointer)
from lga.schema import FlowSpec, Diagnostic
from lga.vectorstores import VectorStoreProvider   # backend protocol (§8b) — custom backends
```

- `create_app()` returns the full FastAPI app (Studio API + A2A + MCP + static); embedders may
  mount subrouters individually: `lga.a2a.router(...)`, `lga.mcp.router(...)`.
- `compile_flow(...).graph` is a vanilla LangGraph `StateGraph` (uncompiled builder also
  accessible) — usable entirely without FastAPI (§1.5-3).
- Nothing in `lga.sdk` may import FastAPI/DB modules (import-linter contract in CI) so
  component packages stay lightweight.

### 2.8 Storage tiers [MUST]

| | SQLite (default) | Postgres (`postgresql+asyncpg://…`) |
|---|---|---|
| When | `lga run` with no config; local PoC | production, docker-compose, `--workers >1` |
| App data | `~/.lga/lga.db` (or `LGA_HOME`) via aiosqlite | same schema via Alembic (dialect-tested both) |
| Checkpoints | `AsyncSqliteSaver` | `AsyncPostgresSaver` |
| Vector stores | `local` backend always available; external backends (qdrant/weaviate/chroma/pgvector-remote) available if extra installed | all backends; `pgvector` may reuse the app DB |
| Concurrency | single process, warn | full |

Selection purely by `LGA_DATABASE_URL` scheme; `lga run` logs the tier prominently.
Vector store availability is **independent of the app-DB tier** (§8b) — the old
"pgvector unavailable on SQLite" coupling from v1 is removed; only the *pgvector backend
pointing at the app DB* requires the Postgres tier.

---

## 3. Core concepts & terminology (normative vocabulary)

| Term | Definition |
|---|---|
| **Component** | Python class (SDK) defining typed inputs/outputs + a `build()` that returns a LangGraph node function. |
| **Node** | An instance of a component placed on the canvas, with configured field values and a pinned component version (§4.11). |
| **Port** | A typed connection point on a node. Input ports come from handle-capable fields; output ports from `Output` declarations. |
| **Edge** | Connection between an output port and an input port. Kinds: `data`, `tool`, `router` (§4.4). |
| **FlowSpec** | Versioned JSON document describing nodes, edges, metadata. The unit of save/export. |
| **Flow** | A stored FlowSpec with identity (`id` + unique `slug`), drafts, versions, lock state. |
| **Flow Version** | Immutable snapshot created by Publish (semver + changelog). A2A/MCP serve *published* versions only. |
| **Agent** | A published flow exposed via A2A. `agent_slug` = flow slug. |
| **Compile** | FlowSpec → validated `StateGraph` (compiled with checkpointer). Deterministic. |
| **Run** | One execution of a compiled flow (full, partial, or background). Has `run_id`, belongs to a thread. |
| **Thread / Session** | LangGraph `thread_id` = Studio `session_id` = A2A `contextId`. One conversation. |
| **Task** | A2A task = one client-visible unit of work; maps 1:1 to a run (or a run-resume chain) (§7.6). |
| **Interrupt** | LangGraph `interrupt()` raised by HITL components; surfaces as A2A `input-required` (§7.7). |
| **Diagnostic** | Structured validation/compile message `{code, severity, node_id, field, message, fix_hint}` (§5.4). |
| **Global Variable** | Server-stored named value; kinds `generic` and `credential` (encrypted) (§10.3). |
| **Tweak** | One-time runtime override of a node field value, passed in run/webhook requests (§9.4). |
| **Vector Store Connection** | Named, server-managed connection to a vector backend (`local`, `pgvector`, `qdrant`, `weaviate`, `chroma`) with collections (§8b). |
| **Template** | A bundled read-only FlowSpec offered in the "new flow" gallery (§9.9). |

---

## 4. Component System (the heart of the framework)

Langflow-inspired surface, strict semantics. A component author writes **one class**; from it
we derive: the node UI form, the input/output ports, edge validation rules, the LangGraph
node function, the optional agent-tool schema, and docs.

### 4.1 Base class [MUST]

```python
# lga/sdk/component.py
class Component(ABC):
    # ---- identity (stability rules in §4.9) ----
    component_id: ClassVar[str]          # REQUIRED, immutable, e.g. "lga.llm.llm_call"
    version: ClassVar[str] = "1.0.0"     # semver of the component itself
    display_name: ClassVar[str]          # shown in sidebar + node header, freely renamable
    description: ClassVar[str]           # sidebar tooltip + docs + default tool description
    icon: ClassVar[str] = "box"          # lucide icon name
    category: ClassVar[str]              # "llm" | "rag" | "flow_control" | "tools" | "io" | "data" | "testing"
    tags: ClassVar[list[str]] = []
    priority: ClassVar[int | None] = None  # palette sort within category (lower first, ties alphabetical)
    documentation_url: ClassVar[str | None] = None
    beta: ClassVar[bool] = False         # renders BETA badge
    legacy: ClassVar[bool] = False       # hidden from sidebar, still loads in old flows

    # ---- interface ----
    inputs: ClassVar[list[Field]]        # §4.2 — order defines form order
    outputs: ClassVar[list[Output]]      # §4.5

    # ---- behavior flags ----
    node_kind: ClassVar[NodeKind] = NodeKind.TASK
    #   TASK      → plain node
    #   ROUTER    → emits control decision; outputs become router branches (amber handles)
    #   INTERRUPT → uses interrupt(); compiler registers HITL semantics (§5.5)
    #   TERMINAL  → e.g. end/ChatOutput; produces flow result artifact
    tool_mode_supported: ClassVar[bool] = False   # can be attached to agents as a tool (§4.7)

    # ---- lifecycle ----
    def build(self, ctx: BuildContext) -> NodeFn: ...      # REQUIRED; returns async node fn
    def on_field_change(self, config: NodeConfig, field_name: str,
                        value: Any) -> NodeConfig: ...     # optional; dynamic fields (§4.6)
    async def health_check(self, ctx: BuildContext) -> None: ...  # optional; used by Validate (deep mode)
    @classmethod
    def migrate_config(cls, old_version: str, config: NodeConfig) -> NodeConfig: ...  # optional (§4.9/§4.11)
```

**`NodeFn` contract [MUST]:** `async def node(state: FlowState, config: RunnableConfig) -> dict`
— a *plain LangGraph node*. It must only read declared inputs (resolved by the wiring layer,
§5.3-P4) and only write declared outputs. The compiled graph must be runnable by vanilla
LangGraph without importing our runtime.

**`BuildContext`** (available at build/compile time):
`ctx.node_id`, `ctx.flow_id`, `ctx.get_field(name)` (resolved value incl. tweaks + global-var
refs), `ctx.secrets.resolve(ref)`, `ctx.vectorstores.get(connection_name)` (§8b),
`ctx.registry`, `ctx.logger`.

**`RunContext`** (available inside NodeFn via `lga.sdk.runtime.get_run_context(config)`):
`emit_status(text)` (→ node status line in UI), `emit_log(level, msg)`, `stream_writer`
(token streaming), `cancellation` token, `run_id`, `thread_id`, `attempt`.

### 4.2 Field classes — the UI input catalog [MUST]

All fields inherit `Field` (Pydantic model). Common attributes (Langflow parity, kept verbatim
where sensible):

```python
class Field(BaseModel):
    name: str                       # python identifier; access via ctx.get_field(name)
    display_name: str
    info: str = ""                  # tooltip
    required: bool = False
    default: Any = None
    advanced: bool = False          # collapsed under "Advanced" in node form
    show: bool = True               # visibility; toggled by on_field_change
    dynamic: bool = False           # participates in on_field_change round-trips
    real_time_refresh: bool = False # triggers on_field_change on every change (else on blur)
    refresh_button: bool = False    # renders ↻ that re-runs on_field_change server-side
    placeholder: str = ""
    tool_mode: bool = False         # exposed as tool argument when node runs as tool (§4.7)
    accepts_global_variable: bool = True   # UI offers ${var} picker
    deprecated: bool = False        # hidden for new nodes, still functional (W301)
    # handle capability:
    as_port: PortSpec | None = None # if set, field is ALSO/ONLY an input port (§4.3)
    port_only: bool = False         # True → no widget, handle only (Langflow HandleInput)
```

Concrete field classes (widget mapping table for the frontend in §11.5):

| Class | Widget | Extra attrs | Notes |
|---|---|---|---|
| `StrInput` | single-line text | `max_length` | |
| `MultilineInput` | textarea (auto-grow) | `max_length` | |
| `IntInput` | number (int) | `min, max, step` | |
| `FloatInput` | number (float) | `min, max, step` | |
| `BoolInput` | toggle | | |
| `SliderInput` | slider | `min, max, step` (required), `min_label`, `max_label` | e.g. temperature ("Precise/Creative" endpoint labels) |
| `DropdownInput` | select | `options: list[str] \| list[Option]`, `combobox: bool` (allow custom), `options_source` (server callback name for dynamic options) | |
| `MultiselectInput` | multi-select | `options` | value: `list[str]` |
| `TabInput` | segmented tabs | `options` (≤5) | mode switches; pairs with `on_field_change` |
| `SecretInput` | password field | | value stored as secret-ref, never echoed back in API reads (§10.3) |
| `MultilineSecretInput` | password textarea | | e.g. service-account JSON |
| `DictInput` | key/value editor | `value_type` | |
| `NestedDictInput` | JSON editor | `schema: dict \| None` (JSON-schema-validated) | |
| `TableInput` | data grid | `columns: list[ColumnSpec]` | |
| `FileInput` | file picker (uploads via Files API §9.6) | `file_types: list[str]`, `multiple: bool` | value = file_id(s) |
| `CodeInput` | code editor | `language` | for e.g. jinja / JSONPath snippets in v1 templating only — **no server-side exec of user python in v1** |
| `PromptInput` | prompt editor | | extracts `{variables}` → **spawns dynamic input ports** per variable (Langflow Prompt behavior) [MUST] |
| `ModelInput` | provider+model picker | `providers: list[str] \| None` | resolves to a `LanguageModel` port value or inline provider config; reads provider creds from global variables |
| `EmbeddingModelInput` | provider+model picker | `providers` | resolves to an `Embedding` handle |
| `VectorStoreInput` | connection + collection picker | `allow_create_collection: bool` | picks a named Vector Store Connection (§8b); collection dropdown via `options_source` |
| `QueryInput` | text with "run" affordance | | search-style inputs, `tool_mode` default True |
| `LinkInput` | read-only hyperlink | `href_from: str` | e.g. OAuth link flows [LATER] |
| `McpInput` | MCP server picker + tool multiselect | | backs `MCP Toolset` (§8.4) |
| `HandleField` | none (port only) | `as_port` required, `port_only=True` | pure connection input |
| `ToolsInput` | none (tool port) | | accepts `Toolset` edges (dashed sky); `is_list=True` implicit |

`Option = {value, label, description?, icon?}`.

**Serialization [MUST]:** `GET /api/v1/components` returns, per component, a JSON descriptor:
identity block + `fields: [ {type: "DropdownInput", ...all attrs} ]` + `outputs` + `node_kind`
+ `priority` + port specs. The frontend renders forms **exclusively** from this descriptor (no
hardcoded per-component UI). JSON Schema for node config values is included as `config_schema`
so the frontend can client-side-validate before hitting `/validate`.

### 4.3 Ports & the type system [MUST]

**PortSpec:**

```python
class PortSpec(BaseModel):
    schema_ref: str            # e.g. "lga:Message", "lga:Documents", "myco:TicketBatch"
    json_schema: dict          # full JSON Schema of the payload (source of truth)
    family: PortFamily         # MESSAGE | DATA | TABLE | DOCUMENTS | EMBEDDING | MODEL |
                               # VECTORSTORE | TOOLSET | ROUTE | FILE | ANY
    is_list: bool = False
    display_name: str | None = None
```

Core port schemas shipped in `lga.sdk.ports` (all Pydantic models with stable JSON Schema):

| schema_ref | Family | Python type | Purpose |
|---|---|---|---|
| `lga:Message` | MESSAGE | `lga.Message` (role, content, name?, metadata, files?) — converts losslessly to/from LangChain `BaseMessage` | chat traffic |
| `lga:Messages` | MESSAGE | `list[Message]` | history segments |
| `lga:Text` | DATA | `str` | plain text |
| `lga:Json` | DATA | `dict[str, Any]` | structured payloads; **edges between two `lga:Json` ports validate structurally** if either side declares a schema |
| `lga:Table` | TABLE | `list[dict[str, Any]]` (uniform keys = columns) | tabular data (Langflow DataFrame parity); rendered as grid in previews |
| `lga:Documents` | DOCUMENTS | `list[Document]` (page_content, metadata, score?) | RAG |
| `lga:Embedding` | EMBEDDING | embedding fn handle (`Embeddings`) | |
| `lga:LanguageModel` | MODEL | `BaseChatModel` handle | model injection |
| `lga:VectorStore` | VECTORSTORE | `VectorStoreHandle` (connection, collection) | store injection (§8b) |
| `lga:Toolset` | TOOLSET | `list[ToolDef]` (name, description, args JSON schema, callable ref) | tool edges |
| `lga:Route` | ROUTE | `str` label | router control — **not user-wirable as data** |
| `lga:FileRef` | FILE | file_id + mime + name | uploaded files |

**Compatibility algorithm (edge validation) [MUST]:**
1. `ANY` matches everything but raises diagnostic `W201` (warning: untyped edge).
2. Same `schema_ref` → compatible.
3. Different refs, same family → compatible iff target JSON Schema accepts source JSON Schema
   (structural subset check via `jsonschema` referencing; cache results).
4. Cross-family → incompatible, **except** registered coercions below.
5. `is_list` mismatch → incompatible unless coercion `T → list[T]` (auto-wrap, emits `W202`).

**Registered coercions (auto-inserted adapters, visible in compile report):**
`Message → Text` (content), `Text → Message` (role=user), `Documents → Text` (formatter with
default template), `Json → Text` (pretty JSON), `Table → Json` (`{rows: [...]}`),
`Table → Text` (markdown table). Everything else requires the explicit `Type Convert`
component (§12.6). Coercions are pure functions in `lga.sdk.ports.coerce`.

### 4.4 Edge kinds [MUST] (matches existing frontend visual language)

| Kind | Visual (§11.3) | Source port family | Semantics |
|---|---|---|---|
| `data` | solid edge | any data family | value flows source→target; compiler maps to state channel (§5.3-P4) |
| `tool` | **dashed sky** edge into agent's Tools handle | TOOLSET | attaches tools to an agent node; no execution ordering implied |
| `router` | edge from **amber** handle | ROUTE (one handle per branch) | conditional edge in LangGraph; exactly-one-taken semantics |

### 4.5 Outputs [MUST]

```python
class Output(BaseModel):
    name: str                    # state channel suffix; stable
    display_name: str
    port: PortSpec
    method: str | None = None    # optional: name of a Component method computing ONLY this
                                 # output (multi-output components, Langflow parity).
                                 # If None, the NodeFn's returned dict must contain `name`.
    group: str | None = None     # UI grouping of outputs
    deprecated: bool = False
```

Router components declare **one Output per branch** with `port=Route` (or a
`dynamic_outputs_from: str` pointing at a field like `labels: MultiselectInput`, in which case
`on_field_change` regenerates outputs — the existing `LLM Router` works this way).

### 4.6 Dynamic configuration (`on_field_change`) [MUST]

Server round-trip identical to Langflow's `update_build_config`, but typed:

```
POST /api/v1/components/{component_id}/config
body: { config: NodeConfig, changed_field: str, value: Any }
→ 200 { config: NodeConfig, fields: [...updated field descriptors...], outputs: [...] }
```

Used for: show/hide dependent fields, refresh dropdown options (`options_source`), regenerate
dynamic ports (Prompt `{vars}`, Router labels, MCP tool lists, vector store collections).
Must be **pure** with respect to config (no writes); may do IO for options (e.g. list MCP
tools, list collections) with a 10s timeout.

### 4.7 Tool mode [MUST]

If `tool_mode_supported`, a node can be attached to an agent via a tool edge. The tool schema
is derived automatically: tool name = node label (slugified, editable in node form via the
implicit `tool_name`/`tool_description` advanced fields — Langflow lesson: **names/descriptions
drive agent tool selection, make them prominent and editable**); arguments = all fields with
`tool_mode=True` (their JSON schema), plus input ports of DATA/MESSAGE family marked
`tool_mode`. Execution: the runtime wraps the NodeFn as a LangChain `StructuredTool` bound to
the run's context (checkpointing captures tool calls as normal graph steps of the agent node).

### 4.8 Registration & discovery [MUST] — no eval, ever

1. **Entry points:** packages expose `[project.entry-points."lga.components"]`; registry
   imports and registers classes at startup.
2. **Component dirs:** `LGA_COMPONENTS_PATH` (colon-separated) is scanned for packages with
   normal `import` machinery (`importlib`), structured `<dir>/<category>/<module>.py` with
   `__init__.py`, ≤2 levels deep, Langflow-style. Files are imported, not eval'd; syntax
   errors become registry diagnostics, not crashes.
3. **Dev hot-reload:** in `LGA_ENV=dev`, watch component dirs (watchfiles); on change
   re-import module, re-emit `GET /components` etag; frontend polls etag and refreshes sidebar.
4. Registry rejects duplicate `component_id` (hard error, lists both origins).

### 4.9 Stability & versioning rules [MUST] (Langflow's contributing lessons, enforced)

- `component_id` is **immutable forever**. Renames touch `display_name` only.
- Removing a field or output is forbidden; deprecate: `deprecated=True` on the Field/Output
  (hidden for new nodes, still functional). Compiler emits `W3xx` when used.
- Breaking behavior ⇒ new `component_id` (e.g. `...llm_call_v2`) + `legacy=True` on old.
- Optional `migrate_config(old_version, config) -> config` classmethod; compiler runs
  migrations when node's stored component `version` < installed version.
- CI check: descriptor snapshot tests fail on any field/output removal (§15.2).

### 4.10 Component test harness [MUST]

`lga.sdk.testing.ComponentTestHarness`:
- `harness.render_descriptor(Component)` → golden-snapshot the JSON descriptor.
- `harness.build(Component, config, secrets={}, ports={...})` → returns callable NodeFn with a
  stub context; assert on returned state delta.
- `harness.run_in_flow(Component, upstream={...})` → micro-flow (start → node → end) compiled
  through the real compiler — catches wiring bugs.
- Fixtures for `FakeLLM`, `FakeEmbeddings`, in-memory checkpointer, in-memory vector store,
  tmp Postgres / qdrant (testcontainers) for integration marks.

### 4.11 Per-node version pinning & guided updates [MUST, M4-UI] (Langflow parity, done right)

Nodes are **detached copies**: `component_version` is pinned at insertion time and never
changes silently (Langflow behavior we keep). What we add on top:

- On flow open, the frontend diffs each node's pinned version against the installed
  component version (from the descriptor) and shows a per-node badge:
  - **Update ready** (installed version has a `migrate_config` path, no removed
    fields/outputs in between): one-click "Update node" runs the migration server-side
    (`POST /flows/{id}/nodes/{node_id}/upgrade`), rewrites config + version, re-validates.
  - **Breaking change** (component is `legacy` and a successor exists): badge links to the
    successor component; "Replace node" inserts the successor with best-effort field mapping
    and keeps the old node disabled alongside for manual porting.
- "Update all" action in the validation panel applies all non-breaking updates.
- Compile always runs migrations transparently (W302) even if the user never clicks update —
  the badge is UX, not a correctness requirement.

---

## 5. FlowSpec, State Model & Compiler

### 5.1 FlowState [MUST]

One shared LangGraph state schema for every compiled flow:

```python
class FlowState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]   # conversation channel
    data: Annotated[dict[str, Any], merge_data]           # shared data dict (Set Data writes here)
    ports: Annotated[dict[str, Any], last_write_wins]     # wiring channels: "{node_id}.{output_name}"
    route: Annotated[dict[str, str], last_write_wins]     # router decisions: node_id -> label
    run_meta: RunMeta                                      # run_id, session, inputs echo (read-only)
```

- `merge_data`: shallow dict merge, key-level last-write-wins; concurrent same-key writes in
  one superstep raise `RT101 DataWriteConflict` (fail fast, deterministic).
- `ports` is **namespaced per node output** — this is the dataflow⇄state bridge. Users never
  see it; the canvas mental model stays "output → input".
- Components must not invent state keys; the wiring layer provides input values and maps
  returned outputs to `ports`/`messages`/`data` as declared.

### 5.2 FlowSpec JSON [MUST]

```jsonc
{
  "schema_version": "2",
  "flow": { "name": "...", "slug": "support-triage", "description": "...", "icon": "bot",
            "tags": [], "locked": false,
            "a2a": { ...§7.4 skill metadata... }, "mcp": { ...§8.1 metadata... } },
  "nodes": [
    { "id": "fake_llm_1",                  // unique, user-visible, stable
      "component_id": "lga.testing.fake_llm",
      "component_version": "1.0.0",        // version pinned at insert → migrations (§4.11)
      "label": "Fake LLM (testing)",
      "config": { "replies": ["hi"] },     // field values; secrets as {"$secret": "name"};
                                           // global vars as {"$var": "name"}
      "position": {"x": 0, "y": 0},
      "notes": "" },
    ...
  ],
  "edges": [
    { "id": "e1", "kind": "data",
      "source": {"node": "start", "output": "message"},
      "target": {"node": "fake_llm_1", "input": "input"} }
  ],
  "ui": { "viewport": {...}, "sticky_notes": [ {id, text, position, color} ] },
  "meta": { "created_at": "...", "modified_at": "..." }
}
```

Reserved node ids: `start`, `end` (implicit ChatInput/ChatOutput semantics; every flow has
exactly one `start`; ≥1 terminal node). JSON Schema for FlowSpec is exported to
`schema/flowspec.schema.json` and versioned; loader migrates older `schema_version`s
(`"1"` → `"2"` migration ships with v2: adds `locked`, `mcp` block; lossless).

### 5.3 Compiler pipeline [MUST] — pure, deterministic, cacheable

```
FlowSpec ──P1 parse──► IR ──P2 resolve──► IR' ──P3 validate──► Diagnostics
                                          │ (no ERRORs)
                                          ▼
                          P4 wire (ports→state channels, coercions, tool binding)
                                          ▼
                          P5 emit StateGraph  (+ interrupt registration, conditional edges)
                                          ▼
                          compile(checkpointer=<tier saver>, durability="async")
```

- **P1 parse:** FlowSpec JSON → typed IR; schema violations → `E0xx`.
- **P2 resolve:** look up components in registry (id+version, run migrations), resolve
  `$secret`/`$var` refs to *handles* (values injected only at run start), resolve vector
  store connection names to handles (§8b), apply tweaks.
- **P3 validate:** rule table §5.4. Severities: ERROR blocks compile; WARNING/INFO pass through.
- **P4 wire:** for each data edge, input resolution = read `state["ports"]["src.out"]`
  (+ coercion fn if registered); tool edges → collect ToolDefs and bind into agent NodeFn;
  PromptInput vars → mapped like data edges.
- **P5 emit:** nodes → `graph.add_node(node_id, node_fn)`; data edges induce ordering edges
  (dedup per node pair); ROUTER nodes → `add_conditional_edges(node_id, route_reader,
  {label: target})` reading `state["route"][node_id]`; INTERRUPT nodes registered (no static
  config needed — `interrupt()` is dynamic); recursion_limit from flow settings (default 50).
- **Determinism:** same FlowSpec bytes + same registry versions ⇒ identical graph & report.
  Compiled graphs cached by `sha256(flowspec) + registry_fingerprint`.
- **Compile report** returned alongside diagnostics: node list, inserted coercions, edge→
  channel map, interrupt points, router tables. Frontend can render this in Debug mode.
- **Induced subgraphs** for partial runs (§6.4) are produced by `compiler/subgraph.py` from
  the same IR — ancestors-of(`until_node`) closure, terminal rewired to `until_node`.

### 5.4 Validation diagnostics [MUST]

`Diagnostic = {code, severity, node_id?, field?, edge_id?, message, fix_hint?}` — rendered in
the existing VALIDATION panel; clicking focuses the node/edge.

| Code | Sev | Rule |
|---|---|---|
| E001 | E | FlowSpec schema invalid / unknown schema_version |
| E002 | E | Unknown `component_id` (registry) — hint: install package / check LGA_COMPONENTS_PATH |
| E003 | E | Duplicate node id / reserved id misuse |
| E010 | E | Required field empty (and not tweakable-at-run) |
| E011 | E | Field value fails JSON schema (wrong type/enum/range) |
| E012 | E | `$secret`/`$var` reference does not exist |
| E013 | E | Vector store connection referenced by node does not exist |
| E014 | E | Credential (`$secret`) assigned to a non-credential (non-Secret) field — a resolved secret must never flow into a plaintext/content field (§10.5) |
| E020 | E | Edge type-incompatible (families/schemas, §4.3) — message includes both schema_refs |
| E021 | E | Tool edge into non-Tools port / from non-Toolset output |
| E022 | E | Router branch label not covered / duplicate branch target label |
| E023 | E | Router output wired as data (ROUTE ports carry control only) |
| E024 | E | Edge into `start` / out of terminal node |
| E030 | E | No `start` node / no terminal node / graph not connected from start |
| E031 | E | Required input port unconnected |
| E032 | E | Cycle contains no ROUTER or INTERRUPT node (guaranteed infinite loop) |
| E040 | E | Interrupt node in a parallel branch set (unsupported in v1: interrupts must be on a single active branch) |
| E060 | E | `a2a.enabled` without agent/skill description (publish gate, §7.4) |
| E062 | E | `mcp.enabled` without tool description (publish gate, §8.1) |
| E063 | E | `mcp.enabled` on flow with INTERRUPT nodes and no interrupt policy (§8.1) |
| W201 | W | ANY-typed edge (untyped) |
| W202 | W | Auto list-wrap coercion inserted |
| W203 | W | Implicit coercion inserted (names it) |
| W301 | W | Deprecated field/output in use |
| W302 | W | Component version migrated (from → to) |
| W401 | W | Node unreachable from start (dead code) |
| I501 | I | Cycle detected — recursion_limit=N applies |

Deep validate (`?deep=true`) additionally runs `health_check()` per node and per referenced
vector store connection → runtime-preflight family:
`E901 BackendExtraMissing` (e.g. `qdrant-client` not installed — hint: `pip install "lga[qdrant]"`),
`E902 VectorStoreUnreachable`, `E903 CollectionMissing`, `E904 EmbeddingDimensionMismatch`
(collection dim ≠ embedding dim), `E905 McpServerUnreachable`, `E906 ModelProviderAuthFailed`.

### 5.5 Control flow mapping [MUST]

- **Routers** (`node_kind=ROUTER`): NodeFn writes `{"route": {node_id: label}}`; compiler
  installs `add_conditional_edges`. `LLM Router` classifies conversation into configured
  labels; `Rule Router` (§12) matches on `data`/message predicates. Router must always emit
  exactly one of its declared labels, else `RT102 RouterInvalidLabel` at runtime.
- **Human-in-the-loop** (`node_kind=INTERRUPT`): NodeFn calls
  `interrupt(InterruptPayload)`. Normative payloads:

```python
class ApprovalRequest(BaseModel):     # Human Approval
    kind: Literal["approval"] = "approval"
    prompt: str
    context: dict[str, Any] = {}
    options: list[str] = ["approve", "reject"]

class InputRequest(BaseModel):        # Human Input
    kind: Literal["free_text"] = "free_text"
    prompt: str
    schema_: dict | None = None       # optional JSON schema for structured input
```

  Resume value: `{"decision": "approve"|"reject", "comment": str|None}` resp.
  `{"text": str}` / schema-conforming dict, delivered via `Command(resume=...)`.
  **These payloads are the single source for Playground modals AND A2A input-required
  messages (§7.7) — do not fork the shape.**
- **Loops:** cycles allowed (E032 guards unguarded ones); `recursion_limit` per flow setting.
- **Subflows:** `Flow as Component` (§12.7) compiles the child flow and embeds it as a
  LangGraph subgraph node; child interrupts propagate. [Milestone M4]

### 5.6 Runtime errors (for completeness)

`RT101 DataWriteConflict`, `RT102 RouterInvalidLabel`, `RT103 NodeException(wrapped)`,
`RT104 Cancelled`, `RT105 RecursionLimit`, `RT106 SecretResolutionFailed`,
`RT107 VectorStoreError(backend, detail)`. Every RT error carries `node_id` and is emitted
on the event stream and stored on the run.

### 5.7 Export to Python [SHOULD, M4]

`GET /api/v1/flows/{id_or_slug}/export?format=python` renders a standalone `flow.py`:
component imports, config literals (secrets as `os.environ[...]`), wiring,
`graph = builder.compile()`. Golden-tested: exported file must produce an identical graph
topology to the compiler.

---

## 6. Runtime & Execution

### 6.1 Run modes [MUST]

| Mode | Entry | Behavior |
|---|---|---|
| `playground` | Studio UI | streams events + tokens; session picker; interrupt modals |
| `api` | `POST /run` / `/webhook` | blocking, SSE stream, or background (§6.5) |
| `partial` | canvas "Run to here" / `until_node` param | §6.4 |
| `debug` | Studio Debug button | interrupt **before every node** (LangGraph `interrupt_before="*"` on a debug-compiled copy); step/continue/abort; inspect+**edit state** between steps (`update_state`) |
| `a2a` | A2A server | §7 |
| `mcp` | MCP tool call | §8; runs blocking with timeout |

All modes share the executor: `execute(flow_version, thread_id, inputs, mode, tweaks,
until_node=None) → run`. Cancellation [MUST]: every run has a token; cancel endpoint + A2A
`tasks/cancel` + client disconnect (configurable) set it; NodeFns must observe it at await
points (the `Slow Node` test component exists precisely to test this).

### 6.2 Event stream [MUST]

SSE (`/api/v1/runs/{run_id}/events`) and internal bus share one envelope:

```jsonc
{ "event": "node_started", "run_id": "...", "thread_id": "...", "seq": 42,
  "ts": "...", "data": { ... } }
```

Events: `run_started`, `node_started{node_id}`, `node_token{node_id, delta}`,
`node_status{node_id, text}`, `node_log{node_id, level, msg}`,
`tool_call{node_id, tool_name, args_preview}`, `tool_result{node_id, tool_name,
result_preview, duration_ms}` (agent tool-loop visibility in the Playground — Langflow parity),
`node_finished{node_id, outputs_preview, duration_ms}`, `node_error{node_id, code, message}`,
`interrupt_raised{node_id, payload}`, `run_resumed`, `run_finished{status, result_preview}`,
`run_cancelled`, `heartbeat` (15s). `seq` is monotonic per run → clients resume with
`Last-Event-ID`. Events are persisted (ring buffer table, 7d retention) to support
reconnect and A2A `tasks/resubscribe`. Previews are truncated at `LGA_MAX_TEXT_LENGTH`.

### 6.3 Checkpointing & sessions [MUST]

- Checkpointer selected by storage tier (§2.8): `AsyncSqliteSaver` (default) or
  `AsyncPostgresSaver` (Postgres), both in the app database, `durability="async"`.
  A `CheckpointerFactory` behind one interface — runtime code never branches on backend.
- `thread_id` = `session_id` = A2A `contextId` (one identifier, minted as UUIDv7 when absent).
- `GET /threads/{id}/state`, `/history` proxy LangGraph state APIs for the Debug UI/time-travel.
- Retention: configurable `LGA_CHECKPOINT_TTL_DAYS` (default 30) with sweeper job.

### 6.4 Partial runs — "Run to node" [MUST, M2] (replaces Langflow's vertex /build API)

Langflow lets users run a single component with its dependency chain (`stop_component_id`).
We provide the same DX on LangGraph semantics without a second execution API:

- `POST /flows/{id_or_slug}/run` accepts `until_node: str`. The compiler builds the induced
  subgraph of `until_node` and all its ancestors; `until_node` becomes the terminal.
- Result artifact = the outputs of `until_node`; all normal events stream (§6.2).
- Canvas UX: hover play button on every node ("Run to here"); result lands in the node's
  output preview drawer (§11.6). Nodes outside the induced subgraph render dimmed during
  the partial run.
- Partial runs use an ephemeral thread by default (`session_id` optional) and are never
  exposed via A2A/MCP.
- There is deliberately **no** `start_component_id` equivalent: runs always start from
  resolved inputs, never from mid-graph state injection (debug `update_state` covers that).

### 6.5 Background runs [MUST, M2] (Langflow Workflow-API parity, minus the job zoo)

`POST /flows/{id_or_slug}/run` with `background: true` → `202 {run_id, thread_id}`
immediately; execution proceeds as asyncio task. Poll `GET /runs/{run_id}` (status, result
when finished) or attach to `GET /runs/{run_id}/events`. Cancel via the normal cancel
endpoint. No separate jobs API, no polling-vs-streaming query params — one run model.

---

## 7. A2A Protocol Compliance [MUST — this section is the contract]

Target: **A2A spec v0.3.x, JSON-RPC 2.0 binding** (declare exact `protocolVersion` from the
pinned a2a-sdk). Use the official `a2a-sdk` Python types/server scaffolding; we implement the
`AgentExecutor` and `TaskStore`. Track the 1.0 field relocations (e.g. extended-card flag
moving into `capabilities`) behind the sdk upgrade — never hand-roll type drift.

### 7.1 Topology: published flow = agent

- Each **published** flow with `a2a.enabled=true` is served as an independent A2A agent at
  `https://{host}/a2a/{agent_slug}` (single JSON-RPC POST endpoint).
- **Serving surfaces are mutually exclusive [MUST].** A published flow is served as an A2A
  agent **XOR** an MCP tool (§8.1) **XOR** a plain REST API — never two at once. The FlowMeta
  invariant enforces this (`FlowMeta._exclusive_serving`, A2A precedence if both are set) and
  exposes the derived `serve_mode ∈ {a2a, mcp, api}`. **A2A is the default surface for a new
  flow.** The Studio Share dialog is a single exclusive mode selector.
- Serving always targets a **pinned published version** (flow setting: `serve: latest_published | vX.Y.Z`).
  Draft edits never change live agent behavior. Republish → agent card `version` bumps.

### 7.2 Transport rules [MUST]

- JSON-RPC 2.0 over HTTPS; request/response `Content-Type: application/json`.
- Streaming methods respond `200 OK`, `Content-Type: text/event-stream`; **each SSE `data:`
  field contains one complete JSON-RPC Response object** (`SendStreamingMessageResponse`).
- HTTPS mandatory in production (`LGA_ENV=prod` refuses to serve A2A over plain HTTP unless
  `LGA_A2A_ALLOW_HTTP=true` for reverse-proxy setups).
- Unknown method → JSON-RPC `-32601`; malformed → `-32700/-32600/-32602` per spec.

### 7.3 Agent Card [MUST]

- Served at `/.well-known/agent-card.json` (0.3.x path) **and** legacy alias
  `/.well-known/agent.json` for 0.2.x clients. For multi-agent hosts:
  the well-known card describes the *directory agent* [LATER]; in v1 each agent's card is at
  `/a2a/{agent_slug}/.well-known/agent-card.json`, and `GET /a2a/{agent_slug}` (no body)
  returns the card too. Document this in README.
- Generated by `lga.a2a.card.build_card(flow_version, settings)`:

```jsonc
{
  "protocolVersion": "<from sdk>",
  "name": "<flow.a2a.agent_name | flow.name>",
  "description": "<flow.a2a.agent_description | flow.description>",
  "url": "https://host/a2a/support-triage",
  "preferredTransport": "JSONRPC",
  "version": "<published semver, e.g. 1.4.0>",
  "provider": {"organization": "<LGA_A2A_PROVIDER_ORG>", "url": "<...>"},
  "capabilities": {
    "streaming": true,
    "pushNotifications": true,
    "stateTransitionHistory": true
  },
  "defaultInputModes": ["text/plain", "application/json"],   // + file mimes if flow accepts FileRef
  "defaultOutputModes": ["text/plain", "application/json"],
  "skills": [ ...§7.4... ],
  "securitySchemes": { "apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"} },
  "security": [ {"apiKey": []} ]            // omitted entirely when flow is public
}
```

- Card content is derived — **never hand-edited JSON**. Editable inputs live in Flow Settings
  → A2A tab (§11.7): agent name/description, skill metadata, auth mode (public | api-key),
  push allowlist.

### 7.4 Skills [MUST]

v1: one flow = one skill (id = flow slug). Skill fields sourced from FlowSpec `flow.a2a`:

```jsonc
{ "id": "support-triage", "name": "Support ticket triage",
  "description": "<what the flow does — REQUIRED before publish with a2a.enabled (E060)>",
  "tags": ["support", "triage"],
  "examples": ["Triage: 'App crashes on login since 2.3.1'"],
  "inputModes": ["text/plain"], "outputModes": ["application/json"] }
```

Publish-time validation: `E060 MissingA2ADescription`, `E061 SkillExamplesRecommended (W)`.
(Langflow lesson from MCP tools: unnamed/undescribed tools wreck agent routing — enforce it.)

### 7.5 RPC methods [MUST implement all]

| Method | Behavior |
|---|---|
| `message/send` | Start or continue a task. Returns `Task` (default) or final `Message` for `blocking:true` fast paths. |
| `message/stream` | Same params; SSE stream of `Task` snapshot → `TaskStatusUpdateEvent`s / `TaskArtifactUpdateEvent`s → terminal event `final:true`. Requires `capabilities.streaming`. |
| `tasks/get` | Return `Task` with `status`, `artifacts`, `history` (respect `historyLength`). |
| `tasks/cancel` | Idempotent; sets cancellation token; `-32002 TaskNotCancelable` if terminal. |
| `tasks/resubscribe` | Re-attach SSE for a live task, replaying from persisted event seq (§6.2). `-32001` if unknown. |
| `tasks/pushNotificationConfig/set` | Store webhook config for task (also accepted inline in `message/send` configuration). |
| `tasks/pushNotificationConfig/get` | Return stored config. |
| `tasks/pushNotificationConfig/list` | List configs for task. |
| `tasks/pushNotificationConfig/delete` | Delete by `pushNotificationConfigId`. |
| `agent/getAuthenticatedExtendedCard` | v1: return same card (no extended fields yet); wire the method so capability flag can be flipped. [LATER: secrets-bearing skill details] |

**MessageSendParams handling [MUST]:** honor `configuration.blocking` (long-poll up to
`LGA_A2A_BLOCKING_TIMEOUT_S`, default 30, then return current Task snapshot),
`configuration.historyLength`, `configuration.acceptedOutputModes` (mismatch →
`-32005 ContentTypeNotSupported`), `configuration.pushNotificationConfig`,
`message.messageId` dedup (same messageId + taskId ⇒ return prior result, don't re-run).

### 7.6 Task lifecycle ⇄ LangGraph mapping [MUST — the core innovation]

| A2A | Ours |
|---|---|
| `contextId` | LangGraph `thread_id` (mint UUIDv7 if client omits; always return it) |
| `taskId` | `a2a_tasks.id`; groups one run + its interrupt-resume chain |
| `submitted` | task row created, run queued |
| `working` | run executing (also after resume) |
| `input-required` | LangGraph `interrupt_raised` — see §7.7 |
| `auth-required` | reserved; emitted by components that need OAuth [LATER] |
| `completed` | run finished; artifacts attached |
| `failed` | RT error; `status.message` carries diagnostic text (no stack traces) |
| `canceled` | via `tasks/cancel` or client-initiated run cancel |
| `rejected` | publish-side guard (agent disabled / version yanked) |

Terminal states are final: a new `message/send` **without** `taskId` on the same `contextId`
starts a *new task in the same thread* (multi-turn conversation, LangGraph checkpoint
continues). `message/send` **with** a terminal `taskId` → JSON-RPC error per spec ("cannot
restart terminal task"). `referenceTaskIds` are stored on the message for traceability.

State machine implemented in `lga/a2a/tasks.py` with explicit transition table; illegal
transitions raise + alert (they indicate executor bugs). `stateTransitionHistory: true` ⇒
persist and expose transitions.

### 7.7 input-required ⇄ interrupt [MUST]

This is the flagship feature — Human Approval / Human Input nodes become protocol-level
multi-turn interactions:

1. NodeFn calls `interrupt(ApprovalRequest|InputRequest)` (§5.5).
2. Executor catches the interrupt event → task → `input-required`;
   `status.message` = agent-role Message with:
   - `TextPart`: the `prompt`
   - `DataPart`: the full typed payload `{kind, options?, schema?, context}` so programmatic
     clients can render forms / auto-answer.
3. Streaming clients receive `TaskStatusUpdateEvent{state: "input-required", final: true}`
   (stream closes per spec; task stays open).
4. Client answers with `message/send {taskId, contextId, message}`. Resume mapping:
   - `kind=approval`: accept `DataPart {decision, comment?}`; else TextPart parsed
     case-insensitively against `options`; unparseable → stay `input-required`, re-prompt
     message explains accepted answers.
   - `kind=free_text`: `DataPart` validated against `schema_` if present, else TextPart→`{text}`.
5. Executor calls `graph.ainvoke(Command(resume=payload), config={thread_id})`;
   task → `working`; stream continues via new `message/stream`/`tasks/resubscribe`.

### 7.8 Message / Part ⇄ FlowState mapping [MUST]

Inbound (`message.parts` → run input):
- `TextPart` → `HumanMessage(text)` appended to `messages`; first TextPart also becomes
  `run_meta.input_text`.
- `DataPart` → merged into `data` under `a2a_input` (and offered to `start` node's optional
  structured-input port).
- `FilePart` → stored via Files service (bytes) or referenced (uri) → `FileRef` list on
  `run_meta.files`; mime allowlist `LGA_A2A_ACCEPTED_MIME`.

Outbound:
- Terminal node result → **one Artifact** `{artifactId, name: "response", parts: [...]}`;
  `lga:Message`/text → TextPart; `lga:Json`/`lga:Table` → DataPart; `FileRef` → FilePart
  (uri to Files API presigned link).
- Intermediate `node_status` events → `TaskStatusUpdateEvent{state: working,
  status.message: TextPart}` (throttled: max 2/s).
- Token streaming: terminal-bound LLM tokens accumulate into an artifact streamed via
  `TaskArtifactUpdateEvent{append: true}` chunks with `lastChunk: true` at end. Flow setting
  `a2a.stream_tokens: bool` (default true).

### 7.9 Push notifications [MUST]

- Storage: `push_configs(task_id, id, url, token, auth_schemes, created_by)`.
- Delivery on transitions to `input-required`, terminal states (and `working` if
  `notify_working=true` in config metadata): HTTP POST of the `Task` object;
  include client `token` as `X-A2A-Notification-Token`.
- **SSRF guard [MUST]:** webhook URLs validated — https only (prod), DNS-resolve and reject
  private/link-local ranges unless `LGA_PUSH_ALLOW_PRIVATE=true`; optional challenge
  (`GET ?validationToken=` echo) before first delivery, per spec guidance.
- Retries: 3 attempts, exp backoff; failures logged on task.
- Capability honesty: if disabled by config, card says `pushNotifications: false` and
  `tasks/pushNotificationConfig/*` return `-32003 PushNotificationNotSupported`.

### 7.10 Errors [MUST — exact codes]

Standard: `-32700, -32600, -32601, -32602, -32603`. A2A-specific:
`-32001 TaskNotFound`, `-32002 TaskNotCancelable`, `-32003 PushNotificationNotSupported`,
`-32004 UnsupportedOperation`, `-32005 ContentTypeNotSupported`,
`-32006 InvalidAgentResponse`. Auth failures are **HTTP-layer** (401/403 + `WWW-Authenticate`),
never JSON-RPC — identity lives in transport headers per spec. Internal diagnostics map to
`-32603` with sanitized message + `data.run_error_code` (RTxxx).

### 7.11 A2A auth [MUST]

Modes per agent: `public` (no auth; **run namespacing** — contextIds are scoped per client
credential/IP-hash so anonymous callers can't address foreign sessions; Langflow CVE-2026-33017
lesson) or `api-key` (`X-API-Key` header validated against §10.4 keys with `a2a:invoke`
scope). Card `securitySchemes/security` generated accordingly. Bearer/OAuth2 [LATER] — keep
`SecurityScheme` union in card builder ready.

### 7.12 A2A client side — `A2A Remote Agent` component [MUST, M3]

Consume other A2A agents from flows (incl. our own → multi-agent):
- Fields: `agent_url` (StrInput, card fetched via `on_field_change` refresh → shows name/
  skills), `auth` (SecretInput), `mode` (TabInput: `node | tool`), `stream` (Bool),
  `timeout_s`, `forward_files` (Bool).
- As **node**: sends conversation tail as message; polls/streams until terminal or
  input-required. Remote `input-required` **propagates**: component raises its own
  `interrupt(InputRequest)` mirroring the remote prompt → our caller (human or upstream A2A
  client) answers → resume forwards to remote task. Nested HITL across agents must work
  end-to-end (example 06 proves it).
- As **tool**: exposed to agents as `call_{remote_slug}` with description from remote card.
- Stores `(remote_task_id, remote_context_id)` in node state for resume across checkpoints.

### 7.13 Compliance testing [MUST] — §15.3.

---

## 8. MCP Surface

### 8.1 Server: published flows as MCP tools [MUST, M3]

- Endpoint: `/mcp` — **streamable HTTP** transport; `/mcp/sse` legacy SSE fallback.
- Tools = published flows with `mcp.enabled=true`. Tool name default = flow slug
  (**never** a UUID); name + description editable in Flow Settings → MCP tab; same
  publish-guards as A2A (`E062 MissingMCPDescription`). Serving is **exclusive** (§7.1):
  `mcp.enabled=true` implies A2A off — a flow is an MCP tool XOR an A2A agent XOR REST-only.
- Tool input schema: derived from flow input contract — default
  `{input_text: string}` + structured `data` properties if the start node declares a schema.
  Tool output: text content (terminal message) + structured content (Json/Table result) per
  MCP spec.
- Execution: blocking run, `LGA_MCP_TIMEOUT_S` (default 120). **Interrupt policy:** flows
  containing INTERRUPT nodes are rejected from MCP exposure (`E063`) unless flow setting
  `mcp.auto_resolve_interrupts = approve|reject` is set (MCP has no input-required concept).
- Auth: `X-API-Key` with `mcp:invoke` scope; `GET /api/v1/mcp/config` returns ready-to-paste
  client JSON (Claude/Cursor style) incl. url + key placeholder.

### 8.2 Tool listing hygiene

`listChanged` notifications on publish/unpublish. Tool descriptions rendered from
flow.a2a/mcp metadata single source (§1.5-2).

### 8.3 MCP client — `MCP Toolset` component (exists in sidebar) [MUST, M2]

- Fields: `server` (McpInput → picks from **globally managed MCP servers**, Settings §11.8:
  name, transport `stdio|streamable_http|sse`, command/args/env or url/headers; secrets via
  `$secret`), `tools` (multiselect, populated via `on_field_change` live tool listing),
  `header_forwarding` (Bool: forward inbound `X-API-Key`/`Authorization` — Langflow parity),
  `timeout_s`.
- Output: `lga:Toolset` → dashed tool edge into agents.
- Env for stdio servers may reference global variables (improve on Langflow's env-only
  limitation).
- Tweaks may override `env`/`headers` at run time (§9.4).

---

## 8b. Vector Store Abstraction [MUST, M2] — new in v2

Langflow ships one component per vector DB vendor, each wrapping a different LangChain class
with divergent parameters. We invert this: **one typed abstraction, named connections,
backends as extras** — the same pattern as MCP servers and model providers.

### 8b.1 Provider protocol

```python
# lga/vectorstores/base.py
class VectorStoreProvider(Protocol):
    backend: ClassVar[str]                     # "local" | "pgvector" | "qdrant" | "weaviate" | "chroma"
    async def health(self) -> None: ...        # raises → E902
    async def list_collections(self) -> list[CollectionInfo]: ...
    async def ensure_collection(self, name: str, dim: int, metric: Metric = "cosine") -> None: ...
    async def upsert(self, collection: str, docs: list[Document],
                     embeddings: list[list[float]]) -> UpsertResult: ...
    async def query(self, collection: str, embedding: list[float], k: int = 4,
                    filter: dict | None = None, score_threshold: float | None = None
                    ) -> list[Document]: ...   # Document.score populated
    async def delete(self, collection: str, ids: list[str] | None = None,
                     filter: dict | None = None) -> int: ...

CollectionInfo = {name, dim, metric, count}
```

- Filters use a **portable subset**: equality + `$in` + `$and` on metadata keys. Each backend
  translates; unsupported filter constructs → `RT107` with a clear message. Backend-specific
  filter passthrough via `raw_filter` advanced field (typed `NestedDictInput`) is allowed but
  emits `W204 BackendSpecificFilter`.
- Custom backends: implement the protocol, register via entry point
  `[project.entry-points."lga.vectorstores"]`.

### 8b.2 Backends & extras

| backend | package (extra) | Connection params | Notes |
|---|---|---|---|
| `local` | `sqlite-vec` (**core dep** — pure wheel, no server; keeps the zero-config promise) | none (file under `LGA_HOME/vectors/`) | default; per-connection db file; works on both storage tiers |
| `pgvector` | `lga[pgvector]` (pgvector + asyncpg) | dsn (or "app database" toggle when tier=Postgres) | table-per-collection, HNSW index |
| `qdrant` | `lga[qdrant]` (qdrant-client) | url, api_key (`$secret`), grpc toggle | |
| `weaviate` | `lga[weaviate]` (weaviate-client v4) | url, api_key (`$secret`) | collections = Weaviate collections |
| `chroma` | `lga[chroma]` (chromadb) | mode: embedded(path) \| http(url, auth) | |

Missing extra at validate/compile → `E901 BackendExtraMissing` with the exact
`pip install "lga[qdrant]"` hint. Backends are imported lazily — importing `lga` must not
import any vendor client (import-linter contract).

### 8b.3 Named connections (server-managed)

- Settings → Vector Stores (§11.8): CRUD named connections `{name, backend, params}`;
  credentials stored as `$secret` refs. `GET /api/v1/vectorstores` lists connections with
  health + collections; `POST /api/v1/vectorstores/{name}/collections` creates one
  (name, dim, metric).
- A default connection `local` (backend `local`) is auto-created on first boot — RAG works
  out of the box with zero configuration.
- Env provisioning: `LGA_VECTORSTORE_<NAME>='{"backend":"qdrant","url":"...","api_key":{"$secret":"QDRANT_KEY"}}'`
  auto-registers connections at boot (deploy parity with `LGA_LOAD_FLOWS_PATH`).
- FlowSpec references connections **by name** (`{"$vectorstore": "prod-qdrant"}`), never by
  credentials — flows stay portable across environments; missing name → `E013`.

### 8b.4 Components (§12.4) use the abstraction

`rag.retriever` and `rag.writer` take a `VectorStoreInput` (connection + collection) plus an
`Embedding` port. Deep validate checks reachability (E902), collection existence (E903), and
embedding-dimension match (E904). The old `pgvector Retriever` sidebar node becomes
`Vector Retriever` with a backend-agnostic connection picker; the prototype's node is
migrated via `migrate_config` (component_id `lga.rag.pgvector_retriever` → marked `legacy`,
successor `lga.rag.retriever`).

---

## 9. Studio REST API (Langflow-informed, trimmed, slug-first)

All under `/api/v1`, auth via `X-API-Key` (or session cookie from the dev UI). OpenAPI
generated; frontend client is generated from it (no hand-written fetch paths).

**Slug-first [MUST]:** every route below that takes `{id}` accepts `{id_or_slug}` — the flow
slug resolves identically to the UUID. Responses always include both. There is deliberately
no `/build` vertex API, no `/monitor` API, and no v1/v2 split: one version, one run model.

### 9.1 Flows & versions
```
GET/POST        /flows                         list/create (drafts); list supports ?tag=&q=
GET/PATCH/DELETE /flows/{id_or_slug}           PATCH rejects edits while flow.locked (409)
POST            /flows/{id_or_slug}/lock       body {locked: bool}
POST            /flows/{id_or_slug}/validate?deep=   → {diagnostics: [...], compile_report?}
POST            /flows/{id_or_slug}/publish    body {version?: "major|minor|patch"|semver, changelog}
GET             /flows/{id_or_slug}/versions   ; GET .../versions/{v}
POST            /flows/{id_or_slug}/versions/{v}/rollback
GET             /flows/{id_or_slug}/export?format=json|python ; POST /flows/import
POST            /flows/{id_or_slug}/nodes/{node_id}/upgrade    (§4.11 guided update)
```
### 9.2 Components
```
GET  /components                    descriptors (etag; §4.2)
POST /components/{cid}/config       on_field_change round-trip (§4.6)
```
### 9.3 Runs, threads, playground
```
POST /flows/{id_or_slug}/run        {input_text?, data?, files?, session_id?, tweaks?,
                                     stream: bool, background: bool, until_node?: str}
                                    → blocking result | SSE (§6.2) | 202 {run_id} (§6.5)
POST /runs/{run_id}/cancel ; GET /runs/{run_id} ; GET /runs/{run_id}/events (SSE, Last-Event-ID)
POST /runs/{run_id}/resume          {payload}    (Playground interrupt answers)
GET  /threads/{tid}/state|/history ; GET/DELETE /threads (session manager)
```
### 9.4 Tweaks & header variables [MUST]
- `tweaks: { "<node_id>": { "<field>": value } }` — validated against field schemas
  (`E011`-equivalent 422), applied at P2 resolve, never persisted. Secrets not tweakable.
- **Header-passed globals** (Langflow parity): `X-LGA-VAR-<NAME>: value` on `/run` and
  `/webhook` overrides the *generic* global variable `<NAME>` for that run only. Credentials
  are never header-settable. Ignored entirely on public (unauthenticated) A2A endpoints.
- `LGA_FALLBACK_TO_ENV_VAR=true` (default false) lets unresolved `$var` refs fall back to
  process env of the same name at run start; misses still raise `RT106`.
### 9.5 Webhook
`POST /webhook/{id_or_slug}` — raw JSON body lands in `data.webhook_payload`; auth
required by default (`LGA_WEBHOOK_AUTH=true`); returns `{run_id}` fire-and-forget
(equivalent to `background: true`).
### 9.6 Files
`POST /files` (multipart, size/mime limits per `LGA_MAX_FILE_SIZE_MB`) → `{file_id}`;
`GET /files/{id}` (presigned-ish tokened URL used in A2A FileParts). Local disk storage v1
(`LGA_FILES_DIR`).
### 9.7 Secrets / global variables — §10.3 CRUD (values write-only).
### 9.8 API keys — §10.4 CRUD. `GET /health` (db+checkpointer+vectorstores), `GET /version`, `GET /config`.
### 9.9 Vector stores & templates
```
GET/POST/DELETE /vectorstores                 named connections (§8b.3); values write-only for secrets
GET             /vectorstores/{name}/collections ; POST … (create: name, dim, metric)
GET             /templates                    bundled starter FlowSpecs (id, name, description, preview)
POST            /flows/from-template/{template_id}
```

---

## 10. Persistence & Security

### 10.1 Tables
`flows(id, slug UNIQUE, …, locked)`, `flow_versions(flow_id, semver, flowspec_jsonb,
changelog, published_at)`, `runs(id, flow_version_id, thread_id, mode, status, error_code,
started/finished)`, `run_events(run_id, seq, jsonb)` (7d TTL), `a2a_tasks(id, context_id,
run_id, state, history_jsonb, artifacts_jsonb)`, `task_transitions`, `push_configs`,
`global_variables`, `api_keys`, `files`, `mcp_servers`, `vector_store_connections`
+ LangGraph checkpoint tables. Local vector data lives outside the app DB in
`LGA_HOME/vectors/*.db` (sqlite-vec files, one per connection).

### 10.2 Migrations: Alembic, autogenerate banned in CI (hand-reviewed).

### 10.3 Global variables & secrets [MUST]
Kinds `generic` | `credential`. Credentials encrypted at rest (Fernet,
`LGA_SECRET_KEY` required in prod, refuse to boot without). API never returns credential
values (write-only; reads return `{name, kind, created_at, in_use_by: [flows]}`). Env
promotion: `LGA_VAR_<NAME>=value` auto-registers generic vars; `LGA_CRED_<NAME>` credentials.
Referenced in configs as `{"$var": name}` / `{"$secret": name}`; resolution at run start
(RT106 on failure). Model providers read standard vars (`OPENAI_API_KEY`, …) via ModelInput.

### 10.4 API keys
`lga_sk_...` random 32B, stored hashed (sha256), scopes: `studio:*`, `a2a:invoke`,
`mcp:invoke`, `webhook:invoke`. Usage tracking (`last_used_at`, `total_uses`,
disable via `LGA_TRACK_APIKEY_USAGE=false`). Revocation immediate. CLI:
`lga apikey create --scopes ...` for headless deploys.

### 10.5 Hardening checklist [MUST]
No user-code eval (§4.8) and no Python-interpreter component (§18.3); prompt templates are
jinja2 **sandboxed** (no attribute traversal); SSRF guards on push + A2A Remote Agent + MCP
http client + `http_request`/`web_search` components (same validator); public-flow session
namespacing (§7.11); FlowSpec `data` param never accepted on public run endpoints (execute
stored definition only); header variables never resolve credentials (§9.4); secrets scrubbed
from logs/events (regex + known-value scrubber); CORS locked to frontend origin.

**Rate limiting / abuse control is a non-goal for the service** — it is delegated to an
upstream gateway (reverse proxy / API gateway) in front of `lga`. The service ships auth
scopes and public-flow session namespacing (§7.11); throttling, IP allow/deny, WAF and DoS
protection belong to the gateway, not the app. Deliberate, to avoid feature creep.

---

## 11. Frontend Specification

§11.1–11.4 define the **design system** (new in v2 — replaces the PoC visuals).
§11.5–11.10 define functional contracts (carried from v1, extended).

### 11.1 Design foundations [MUST]

**Intent.** This is an instrument panel for people who read Python: quiet, precise, dense
where it matters, with exactly one expressive moment (live edges, §11.4). The PoC's decorative
space-purple glow, gradient sliders, and floating unlabeled ports are retired. Dark-first;
a light theme is [SHOULD, M4] and must derive from the same tokens.

**Typography — self-hosted via `@fontsource`, bundled in the wheel (no CDN, works offline):**

| Role | Face | Package | Usage |
|---|---|---|---|
| UI | **Instrument Sans** (variable) | `@fontsource-variable/instrument-sans` | everything: node titles (13px/600, tracking -0.01em), field labels (12px/500), body (13px/450), sidebar (13px), buttons |
| Mono | **JetBrains Mono** (variable) | `@fontsource-variable/jetbrains-mono` | node ids, slugs, `schema_ref`s, diagnostics codes, JSON/code editors, API snippets — 11–12px |

Rules: `font-feature-settings: "tnum"` (tabular numerals) on all numeric readouts (durations,
token counts, slider values); no font below 10.5px; line-height 1.45 body / 1.2 headings;
never letter-space mono. Type scale (px): 10.5 · 12 · 13 · 14 · 16 · 20 · 24.

**Color tokens (dark theme, normative — Appendix C ships the Tailwind v4 `@theme` file):**

| Token | Value | Use |
|---|---|---|
| `--canvas` | `#0E1116` | workspace background (graphite, *not* purple) |
| `--surface-1` | `#151A21` | node body, sidebar, panels |
| `--surface-2` | `#1C232D` | inputs, node header, hover rows |
| `--surface-3` | `#232C38` | active/pressed, dropdown items |
| `--border` | `#2A3340` | 1px default border |
| `--border-strong` | `#3A4553` | input borders, dividers on surface-2 |
| `--text-1` | `#E8ECF2` | primary text |
| `--text-2` | `#9AA4B2` | labels, secondary |
| `--text-3` | `#6B7482` | placeholders, disabled |
| `--accent` | `#8B7CF7` | selection ring, primary buttons, focus, running hairline |
| `--accent-muted` | `#8B7CF7` @ 14% | selected-node header tint, active sidebar item |
| `--success` | `#4ADE80` | finished state, publish |
| `--warning` | `#FBBF24` | warnings, router amber shares this hue |
| `--danger` | `#F87171` | errors |

Canvas texture: 24px dot grid, dots `--border` at 45% opacity, dots fade out below 60% zoom.
No radial glows, no gradients on chrome. Shadows: nodes `0 1px 2px rgb(0 0 0/.4), 0 8px 24px
rgb(0 0 0/.28)`; popovers one step stronger. Radii: node 12px, panel 10px, input/button 8px,
chip 6px, handle 999px. Spacing: 4px base grid; node inner padding 12px; field gap 10px.

**Port family palette [MUST]** (fixed; drives handle ring, edge stroke, port label chip,
sidebar type hints — carried from v1, extended):

| Family | Color | | Family | Color |
|---|---|---|---|---|
| MESSAGE | indigo `#818CF8` | | MODEL | cyan `#22D3EE` |
| DATA | slate `#94A3B8` | | VECTORSTORE | fuchsia `#E879F9` |
| TABLE | teal `#2DD4BF` | | TOOLSET | sky `#38BDF8` (dashed edges) |
| DOCUMENTS | emerald `#34D399` | | ROUTE | amber `#FBBF24` |
| EMBEDDING | violet `#A78BFA` | | FILE | orange `#FB923C` |
| | | | ANY | gray `#6B7482`, dashed ring |

Color is never the only encoding [MUST]: `is_list` ports render as diamonds (square rotated
45°), scalar ports as circles, ANY as dashed circle, ROUTE as amber circle on the right edge;
every port shows a text label; hover reveals `schema_ref` + schema summary.

### 11.2 Node anatomy [MUST]

Default width 288px (grid-snapped); min 240, resizable [SHOULD].

```
┌────────────────────────────────────────────┐
│ ▪icon  Prompt Template            ⌄ ⋯      │  header 40px, surface-2, radius-t 12
│        prompt_template_1                   │  ← id in mono 10.5px text-3 (hover/selected)
├────────────────────────────────────────────┤
│  Template                                  │  field label 12px text-2
│  ┌──────────────────────────────────────┐  │
│  │ Summarize {context} for {audience}   │  │  input on surface-2, border-strong
│  └──────────────────────────────────────┘  │
│ ◇ context                                  │  dynamic input ports: labeled rows, 28px,
│ ◇ audience                                 │    diamond/circle handle ON the left border
│                                            │
│                              text ○        │  output rows right-aligned, handle ON the
│                           message ●        │    right border, family-colored ring
├────────────────────────────────────────────┤
│ ✓ 128ms                        v1.2.0 ⚠︎   │  footer 24px: last-run chip · version badge
└────────────────────────────────────────────┘
```

- **Header:** 24px icon chip, rounded-md, background = category color @ 12%, icon = category
  color; title 13px/600; kebab menu (rename, duplicate, disable, docs, delete); collapse
  chevron folds body to header+ports [SHOULD].
- **Handles:** 10px, centered on the node border (not floating beside it — fixes PoC
  screenshot 2), fill `--surface-1`, 1.5px ring in family color; connected → filled with
  family color; 16px invisible hit area. Geometry per §18.4: data in left · data out +
  router branches right · control-in + toolset-out top · tools-in bottom.
- **Fields:** widgets per §11.5. Sliders: flat track (`--border-strong`), fill `--accent`,
  12px thumb, value in tabular mono right-aligned, optional `min_label`/`max_label`
  endpoints (replaces the PoC pink gradient slider). Advanced fields collapse under a
  disclosure ("Advanced · n").
- **Footer:** appears after first run or when versioned info exists — last-run state chip
  (✓ duration / ✗ error code), version badge with §4.11 update indicator (`⚠︎ update`).
- **Badges** (top-right, stacked): red error count / amber warning count (click → validation
  panel), BETA, LEGACY, debug breakpoint dot.

**States [MUST]:** default 1px `--border` · hover `--border-strong` · selected 1.5px
`--accent` ring + `--accent-muted` header tint · **running** 2px animated accent hairline
across the node top + spinner replacing the icon · finished flash `--success` ring 600ms ·
error persistent 1.5px `--danger` ring + badge · disabled 45% opacity + "disabled" chip ·
dimmed (outside a partial-run subgraph, §6.4) 35% opacity.

### 11.3 Edges & canvas [MUST]

- Data edges: 1.75px bezier, stroke = **source** family color @ 70%; hover/selected 2.5px @
  100% + endpoint dots. Tool edges: dashed (6/4) sky. Router edges: amber from branch handles.
- Coercion marker: when the compiler inserted an adapter (W202/W203), render a small circled
  `≈` at edge midpoint; tooltip names the coercion.
- Drag interactions: on connect-drag, incompatible handles dim to 25% (client-side family
  check), compatible ones scale 1.15; exact structural verdict from `/validate` on drop;
  dropping on empty canvas opens the filtered "compatible components" quick-add (Langflow
  parity). Invalid drop → edge snaps back + toast with the E020 message.
- Selection: marquee, shift-click multi; alignment smart-guides while dragging [SHOULD].

### 11.4 Motion & accessibility [MUST]

- Signature moment — **live edges:** while a run is active, edges on the active path animate
  a slow dash-flow (dash 2/6, 900ms linear loop) in the family color; everything else stays
  still. This is the one animated flourish; do not add ambient canvas effects.
- Durations: micro 120ms, panel/drawer 200ms, easing `cubic-bezier(.2,0,0,1)`. Token
  streaming in the Playground has no per-character animation.
- `prefers-reduced-motion`: disable live edges (static 70%-opacity highlight instead),
  disable running hairline animation (static bar), keep instant state changes.
- Keyboard: every canvas action reachable (§11.9); visible 2px `--accent` focus ring on all
  interactive elements including handles; port tooltips readable by screen readers
  (`aria-label` = "output message, type lga:Message"). Text contrast ≥ 4.5:1 on its surface
  (token pairs verified by a CI contrast test over the palette).

### 11.5 Form generation [MUST]

One `FieldWidgetRegistry: Record<FieldType, React.FC<WidgetProps>>` mapping every §4.2 field
type to a widget; node inspector renders purely from the component descriptor. Unknown field
type → fallback JSON widget + console warn (forward compat). `advanced` fields collapse;
`show=false` hidden; `dynamic|real_time_refresh|refresh_button` wire to
`POST /components/{cid}/config` with 300ms debounce and optimistic UI.
TypeScript types for descriptors/FlowSpec/diagnostics/events are **generated** from backend
OpenAPI + exported JSON schemas (`npm run gen:api`); hand-written mirrors are forbidden.
Styling comes exclusively from §11.1 tokens via Tailwind utilities — no per-widget hex values
(CI greps for raw hex outside the token file).

### 11.6 Validation panel & node previews [MUST]

- Diagnostics list grouped by severity; click → focus/flash node, open offending field;
  node badges; Publish disabled while ERRORs exist; deep-validate toggle; "Update all"
  action for §4.11. Panel exists — bind it to the real `/validate` contract.
- **Output preview drawer:** after any run (full or partial §6.4), each executed node gets an
  inspectable outputs preview — Message as chat bubble, Json as collapsible tree, Table as
  data grid, Documents as scored list. Truncated at `LGA_MAX_TEXT_LENGTH` with "open full".

### 11.7 Playground, Debug, Publish & Share [MUST]

- Right-drawer chat: streams §6.2 events; token streaming into the assistant bubble;
  **tool-call blocks** (collapsed `tool_call`/`tool_result` pairs with args/result previews —
  agent transparency, Langflow parity); per-node timeline (started/finished/duration/status,
  expandable logs & previews); **interrupt modals** rendered from `ApprovalRequest`/
  `InputRequest` payloads (buttons from `options`, form from `schema_`); session dropdown
  (threads API) with rename/delete; raw state inspector.
- Debug mode: same drawer + Step / Continue / Abort, node highlighting on current step,
  state inspector with **edit state** (guarded by confirm) via `update_state`.
- Publish dialog: semver bump selector + changelog + blocking diagnostics summary.
- Share/Serve dialog tabs — **A2A** (enable, agent name/description, skills editor, auth
  mode, live agent-card preview, curl + a2a-sdk python snippets), **MCP** (enable, tool
  name/description, client-config JSON, interrupt policy), **API** (curl/python for `/run`
  + webhook, tweaks example). Snippets always use the **slug**.

### 11.8 Settings pages

Global Variables (create generic/credential; usage list), API Keys, MCP Servers manager
(§8.3), **Vector Stores manager** (§8b.3: connections, health dot, collections table with
dim/metric/count, create collection), Model Providers (thin: provider → credential var
mapping), Appearance (theme, density [SHOULD]).

### 11.9 Keyboard shortcuts [SHOULD, M4] (discoverable via `?` overlay)

`/` insert component palette · `⌘K` command palette · `⌘S` save · `⌘Z/⇧⌘Z` undo/redo ·
`⌘D` duplicate selection · `⌫` delete selection · `⌘A` select all · `⌘0/⌘=/⌘-` zoom
fit/in/out · `⌘Enter` run flow · `⇧Enter` (node focused) run to node · `V` validate ·
`P` playground · arrows nudge selection 8px (⇧ = 24px).

### 11.10 Canvas niceties [SHOULD, M4]

Sticky notes (in FlowSpec.ui), undo/redo (zustand temporal), copy/paste nodes with config
(secrets stripped), minimap, auto-layout button (dagre), template gallery on empty state
(§9.9), lock indicator when `flow.locked`.

---

## 12. Built-in Component Catalog v1

Every component: full descriptor, harness tests, docstring page. Existing sidebar names are
canonical. (component_id prefix `lga.`)

### 12.1 IO & Glue
| id | Notes |
|---|---|
| `io.start` (Chat Input) | outputs `message: Message`, optional structured `data: Json` (declared schema feeds A2A/MCP input contracts) |
| `io.end` (Chat Output) | TERMINAL; inputs `message|text|json|table`; formats final artifact |
| `io.text_input` / `io.text_output` | plain text variants |
| `io.set_data` (exists) | writes literal/jinja-templated values into `data`; TableInput of key/template rows |
| `io.webhook_input` | exposes `data.webhook_payload` typed via optional schema |

### 12.2 LLM
| id | Notes |
|---|---|
| `llm.language_model` (exists) | **Dual-role (Langflow parity):** ModelInput + `input: Message` + `system_message`. Wire an Input → it *runs* the model, emitting `message: Message` / `text: Text` (Model Response); the `model: Model` handle is always exposed (carries the provider *config dict*, not a client) for an Agent/Router. Runs only when an Input is wired, so handle-only use is a cheap config pass-through. |
| `llm.llm_call` (exists) | one-shot completion; PromptInput (dynamic {var} ports), ModelInput, structured-output toggle (Json schema) |
| `llm.llm_agent` (exists) | tool-loop agent (LangGraph prebuilt ReAct under the hood); ToolsInput; system PromptInput; max_iterations; emits `tool_call`/`tool_result` events (§6.2) |
| `llm.structured_output` | force Json/Table per schema from a model (TableInput schema editor: name, description, type — Langflow parity) |
| `testing.fake_llm` (exists) | scripted replies (cycles `replies`), optional scripted tool_calls; zero-dep CI backbone |

### 12.3 Flow Control
| id | Notes |
|---|---|
| `flow.llm_router` (exists) | ROUTER; labels via MultiselectInput → dynamic ROUTE outputs |
| `flow.rule_router` | ROUTER; predicate table on data/message (jinja/JSONPath) |
| `flow.human_approval` (exists) | INTERRUPT; ApprovalRequest |
| `flow.human_input` (exists) | INTERRUPT; InputRequest (+optional schema) |
| `flow.loop_until` [M4] | cycle helper with counter guard |

### 12.4 RAG (backend extras per §8b.2; embeddings via provider extras)
| id | Notes |
|---|---|
| `rag.retriever` | VectorStoreInput (connection+collection) + Embedding port + query; k, portable filter (Json), score_threshold, `raw_filter` (advanced, W204) → Documents; `tool_mode_supported` |
| `rag.writer` | Documents + Embedding → collection (ensure_collection with dim from embedding); upsert receipt Json |
| `rag.embeddings` | EmbeddingModelInput → Embedding handle |
| `rag.text_splitter` | Documents/Text → Documents (chunk_size, overlap, separators) |
| `rag.file_loader` | FileInput → Documents; txt/md/pdf/csv/json |
| `rag.directory_loader` [M4] | server-side directory glob → Documents |
| `rag.pgvector_retriever` (exists in prototype) | `legacy=True`; migrate_config → `rag.retriever` (§8b.4) |

### 12.5 Tools
`tools.mcp_toolset` (exists, §8.3) · `tools.a2a_remote_agent` (§7.12) ·
`tools.flow_as_tool` [M4] (published flow → Toolset entry) · `tools.calculator` (safe AST
eval demo tool) · `tools.http_request` (GET/POST with SSRF guard; tool_mode) ·
`tools.web_search` [M4] (provider-agnostic: DropdownInput provider ∈ {tavily, serpapi,
searxng-url}; creds via `$secret`; → Table; tool_mode).

### 12.6 Data
`data.prompt_template` (PromptInput standalone → Text/Message) · `data.type_convert`
(explicit conversions incl. Documents→Text template, Table⇄Json, Message⇄Text — Langflow
Type Convert parity) · `data.json_extract` (JSONPath) · `data.parser` (regex/split → Json) ·
`data.message_history` (reads the checkpointed thread: n_messages, sender filter → Messages
or Table — Langflow Message History parity; no external memory backends in v1) ·
`data.current_date` (timezone dropdown → Text; tool_mode) · `data.for_each` (maps a
sandboxed jinja template over each item of a list → per-item Table + joined Text; the v1
map/aggregate primitive — a `Send`-based canvas-subgraph body remains §5.5 [M4]).

### 12.7 Testing
`testing.slow_node` (exists; sleeps `seconds`, checks cancellation each 100ms) ·
`testing.failing_node` (raises configured error at configured step — exercises RT103 + A2A
`failed`) · `testing.echo_data` · `testing.fake_embeddings` (deterministic hash embeddings,
configurable dim — makes RAG examples run without API keys) · `testing.mock_data` (Lorem
message / sample Json / 50-row Table — Langflow Mock Data parity).

---

## 13. `examples/` folder [MUST]

Structure per example:
```
examples/NN_name/
  flow.json          # FlowSpec, importable via POST /flows/import
  README.md          # what it shows, how to run, expected transcript
  seed.py            # optional: data seeding (e.g. vector collection)
  test_example.py    # pytest: import → validate (0 errors) → publish → run → assert transcript
```
`examples/run_all.sh` imports+tests everything against docker-compose. Examples 01/02/03/04/
05/06 use **fake_llm / fake_embeddings + local vector store only** (CI without API keys or
external services); provider/backend variants marked `requires: [openai]` / `requires: [qdrant]`.

| # | Name | Demonstrates |
|---|---|---|
| 01 | `hello_flow` | start → fake_llm → end; validate/run/SSE basics |
| 02 | `agent_with_tools` | llm_agent + calculator + http_request tool edges; tool_call events in Playground |
| 03 | `rag_local` | seed script → rag.writer (local sqlite-vec) + fake_embeddings; retriever + prompt template with {context} port; **variant `rag_qdrant`** (same flow.json, connection swapped via env, `requires: [qdrant]`, docker-compose profile) |
| 04 | `hitl_approval_a2a` | human_approval; **full A2A input-required round-trip via a2a-sdk client script** (`client.py` included) |
| 05 | `router_branches` | llm_router (3 labels) + rule_router fallback |
| 06 | `multi_agent_a2a` | orchestrator flow calling examples 03+05 as A2A Remote Agents; nested interrupt propagation |
| 07 | `mcp_toolset_client` | agent using external MCP server (ships a tiny FastMCP demo server) |
| 08 | `flow_as_mcp_tool` | publish 03 with mcp.enabled; Claude/Cursor config snippet in README |
| 09 | `custom_component` | separate installable package `examples/09_custom_component/pkg` with entry point; a `TicketBatch` custom port schema proving structural typing (E020 demo) |
| 10 | `headless_python` | compile+run a FlowSpec (and the §5.7 export) with zero frontend |

---

## 14. Configuration (env)

Every var has a matching CLI flag where it makes sense (§2.6); precedence: flag > env >
`--env-file` > `./.env` > default. `Settings` (pydantic-settings) is the single loader —
no scattered `os.environ` reads (CI-linted).

| Var | Default | |
|---|---|---|
| `LGA_ENV` | `dev` | dev enables hot-reload, http A2A |
| `LGA_HOST` / `LGA_PORT` | `127.0.0.1` / `8000` | bind address (`lga run --host/--port`) |
| `LGA_HOME` | `~/.lga` | SQLite db, vector files, files, logs default root |
| `LGA_DATABASE_URL` | `sqlite+aiosqlite:///~/.lga/lga.db` | Postgres URL switches tier (§2.8) |
| `LGA_SECRET_KEY` | auto-generated → `~/.lga/secret_key` (dev) | Fernet; explicit value required in prod |
| `LGA_HOST_URL` | `http://{host}:{port}` | public base URL for agent cards / file links |
| `LGA_COMPONENTS_PATH` | — | extra component dirs (colon-separated) |
| `LGA_FRONTEND_PATH` | bundled `_static/` | dev override (§2.5) |
| `LGA_LOG_LEVEL` / `LGA_LOG_FILE` | `info` / — | |
| `LGA_AUTH_ENABLED` | `false` dev / `true` prod | Studio API auth |
| `LGA_A2A_BLOCKING_TIMEOUT_S` | 30 | |
| `LGA_A2A_ACCEPTED_MIME` | `text/plain,application/json,application/pdf,image/*` | |
| `LGA_PUSH_ALLOW_PRIVATE` | `false` | SSRF |
| `LGA_MCP_TIMEOUT_S` | 120 | |
| `LGA_WEBHOOK_AUTH` | `true` | |
| `LGA_CHECKPOINT_TTL_DAYS` | 30 | |
| `LGA_FILES_DIR` | `~/.lga/files` | |
| `LGA_VAR_*` / `LGA_CRED_*` | — | §10.3 |
| `LGA_VECTORSTORE_<NAME>` | — | JSON connection descriptor (§8b.3) |
| `LGA_FALLBACK_TO_ENV_VAR` | `false` | §9.4 |
| `LGA_LOAD_FLOWS_PATH` / `LGA_LOAD_FLOWS_OVERWRITE` / `LGA_LOAD_FLOWS_PUBLISH` | — / `false` / `false` | boot-time flow provisioning (§18.1) |
| `LGA_CREATE_STARTER_FLOWS` | `true` | seed template flows into empty DB |
| `LGA_AUTO_SAVING` / `LGA_AUTO_SAVING_INTERVAL_MS` | `true` / `1000` | Studio autosave; exposed via `GET /config` |
| `LGA_MAX_FILE_SIZE_MB` | `50` | Files API limit |
| `LGA_MAX_TEXT_LENGTH` | `300` | preview truncation |
| `LGA_SSL_CERT_FILE` / `LGA_SSL_KEY_FILE` | — | TLS for `lga run` (passed to uvicorn) |
| `LGA_TRACK_APIKEY_USAGE` | `true` | §10.4 |

---

## 15. Testing & CI [MUST]

1. **Unit**: fields serialization, port compatibility matrix (golden table incl. Table +
   VectorStore families), coercions, FlowSpec schema (+ v1→v2 migration), diagnostics.
2. **Compiler goldens**: fixture FlowSpecs → expected diagnostics + graph topology snapshots
   (node/edge/conditional tables, induced subgraphs for `until_node`); component descriptor
   snapshots (back-compat gate §4.9).
3. **A2A compliance suite** (`tests/a2a/`): pytest against a live test server using the
   official `a2a-sdk` client — card served on both well-known paths & validates against sdk
   types; every §7.5 method incl. all error codes (-32001…-32006, -32601, -32700); SSE
   framing (each `data:` = complete JSON-RPC response; `final` flags); blocking semantics;
   messageId dedup; multi-turn contextId continuation; **input-required round-trip**
   (approval + structured input); resubscribe replay after dropped stream; cancel during
   slow_node; push delivery to a local webhook receiver incl. SSRF rejection cases; auth 401
   paths. This suite is the definition of "A2A erfüllt".
4. **MCP suite**: list/call via mcp client; schema fidelity; interrupt-policy rejection E063.
5. **Vector store suite**: protocol conformance test parameterized over backends — `local`
   always; `pgvector`/`qdrant`/`weaviate`/`chroma` via testcontainers behind pytest marks
   (skipped when extra absent); upsert/query/filter/threshold/delete semantics identical
   across backends; E901–E904 deep-validate paths; W204.
6. **E2E**: docker-compose up → `examples/run_all.sh`; Playwright smoke on frontend
   (drag, connect incompatible → blocked, validate panel shows E020, run-to-node preview,
   publish, playground run + tool-call block, approval modal).
7. **Design tokens**: CI greps for raw hex values outside the token file; automated contrast
   check (§11.4) over token pairs; visual regression screenshots [SHOULD] of one node per
   state (default/selected/running/error) via Playwright.
8. **Packaging & CLI suite** [MUST]: build wheel in CI → install into a **fresh venv without
   Node** → assert `_static/index.html` + bundled fonts present, `lga version` works,
   `lga run --port 0 --no-open` boots to healthy `/health` on SQLite with zero config
   (incl. auto-created `local` vector connection), `lga init` scaffold is valid,
   `lga flow validate examples/01…` exits 0/3 correctly, `uvx --from ./dist/*.whl lga
   version` works; API-surface snapshot for §2.7 public imports; import-linter contracts
   (sdk must not import fastapi/db; `import lga` must not import vendor vector clients);
   DB test matrix runs unit+compiler+A2A suites on **both** SQLite and Postgres backends.
9. CI matrix: py3.12/3.13; `uv`; ruff+mypy(strict on sdk/compiler/a2a/vectorstores);
   testcontainers (postgres, qdrant).

---

## 16. Milestones (weeks)

| M | Week | Deliverable | Exit criteria |
|---|---|---|---|
| M0 | 1 | Package skeleton + **CLI skeleton (`run/init/version/config`)** + wheel build hook (frontend bundling) + SDK core (Component/fields/ports/registry/harness) + FlowSpec v2 + compiler P1–P5 + diagnostics + **§11 token system & node shell in the frontend** | `uvx --from dist lga run` serves bundled frontend on SQLite, zero config; example 01 compiles headless via `lga flow validate --local`; nodes render per §11.2 anatomy |
| M1 | 2 | Runtime: executor, tiered checkpointer, SSE events, cancel, interrupts; Playground bind (incl. tool-call blocks); testing components; `lga flow run` | examples 01/05 run in UI; approval modal works; debug stepping |
| M2 | 3 | **A2A server complete** (§7) + compliance suite green + **vector store abstraction** (local + one external backend end-to-end) + partial & background runs + MCP Toolset client | example 04 round-trip via a2a-sdk client passes in CI on both DB tiers; example 03 (local) green; run-to-node works on canvas |
| M3 | 4 | MCP server + A2A Remote Agent + remaining vector backends (qdrant/weaviate/chroma/pgvector) + secrets/API keys/publish versions + `lga apikey/migrate/component new` | examples 03-qdrant/06/07/08 pass; Share dialogs live; vector suite green across backends |
| M4 | 5–6 | Catalog fill (routers, converters, message history, web search, mock data), export-to-python, flow-as-tool, node update UX (§4.11), template gallery, shortcuts, canvas niceties, docs, example 09/10, **PyPI release pipeline (TestPyPI → PyPI)** | full example matrix green; `pip install lga` from TestPyPI quickstart ≤10 min |

---

## 17. Acceptance checklist (v1 done =)

- [ ] All §15.3 A2A compliance tests pass against `docker compose up`.
- [ ] Agent card auto-generated, valid per a2a-sdk types, served on both well-known paths.
- [ ] Human Approval on canvas ⇒ `input-required` over A2A ⇒ resume ⇒ `completed`, artifacts correct.
- [ ] Incompatible edge is impossible to publish: E020 with both schema_refs named.
- [ ] Fresh machine, no Node, no Docker: `uv tool install lga && lga run` → browser opens the
      full Studio on SQLite with zero config; RAG example works against the auto-created
      `local` vector connection with `fake_embeddings`; `.env` + `--port`/`--env-file`
      respected per §2.6 precedence.
- [ ] `pip install lga && lga flow run examples/01_hello_flow/flow.json --local` works with zero API keys.
- [ ] `pip install "lga[qdrant]"` + one env var (`LGA_VECTORSTORE_PROD=…`) switches example 03
      to Qdrant without touching the FlowSpec.
- [ ] `lga init` workspace + `lga component new` package registers via entry point and appears in the sidebar.
- [ ] Published flow callable as MCP tool from Claude Code using the generated config snippet.
- [ ] No `eval`/`exec` of user-supplied code anywhere (grep-gated in CI).
- [ ] Compiled graph from export-to-python runs under vanilla LangGraph.
- [ ] No raw hex colors outside the token file; node states render per §11.2; live-edge
      animation disabled under `prefers-reduced-motion`.
- [ ] Every documented endpoint accepts the flow slug wherever it accepts the UUID.

---

## 18. Langflow parity addendum (updated 2026-07-07)

Sourced from docs.langflow.org (concepts-components, data-types, concepts-objects,
components-custom-components, contributing-components, api-reference, workflow-api,
components-io/processing/helpers/vector-stores, bundles, concepts-publish, concepts-flows,
environment-variables). Rules: adopt what fits the lga architecture, map names to `LGA_*`,
reject multi-user/telemetry/marketplace features by design. This table is normative.

### 18.1 Adopted (mapped)

| Langflow feature | lga mapping |
|---|---|
| Env vars `LOAD_FLOWS_PATH`, `CREATE_STARTER_PROJECTS`, `AUTO_SAVING(+_INTERVAL)`, `MAX_FILE_SIZE_UPLOAD`, `MAX_TEXT_LENGTH`, SSL files, `LOG_FILE` | §14 `LGA_*` equivalents |
| `FALLBACK_TO_ENV_VAR`, header-passed global variables (`X-LANGFLOW-GLOBAL-VAR-*`) | §9.4 (`X-LGA-VAR-*`, generic vars only, never credentials) |
| Component `priority`, category dirs ≤2 levels, hot-reload, `self.status`/`self.log` → `emit_status`/`emit_log`, `update_build_config` → `on_field_change` | §4.1/§4.8/§18.2-v1 unchanged |
| Detached per-node component versions + "Update ready / Breaking change" notifications | §4.11 (with server-side `migrate_config` instead of silent divergence) |
| Run single component / `stop_component_id` | §6.4 partial runs (`until_node`) — no vertex API |
| Workflow API `background=true` + job polling + stop | §6.5 background runs on the one run model |
| Endpoint name alias for `/run/$FLOW_ID` | §9 slug-first everywhere (superset) |
| DataFrame data type | `lga:Table` port (§4.3) |
| Unified **Language Model** component (dual outputs: *Model Response* + *Language Model* handle) + canonical Chat Input → Language Model → Chat Output flow | §12.2 `llm.language_model` dual-role (runs on `input`, always exposes the `model` handle); `io.start`/`io.end` present as **Chat Input**/**Chat Output** |
| Type Convert, Structured Output schema table, Message History, Mock Data, Current Date, Web Search | §12 catalog |
| Playground agent tool-call visibility | `tool_call`/`tool_result` events (§6.2) + Playground blocks (§11.7) |
| Templates / starter projects | §9.9 template gallery + `LGA_CREATE_STARTER_FLOWS` |
| Lock Flow | `flow.locked` + `/lock` endpoint (§9.1) |
| Port hover details, click-port → compatible-component search, smart guides, keyboard shortcuts | §11.3/§11.9 |
| Vector store breadth (Qdrant, Weaviate, Chroma, PGVector, local default DB) | §8b unified abstraction; Langflow's ~15 further vendors [LATER] as external component packages |

### 18.2 Deferred [LATER]

OpenAI-Responses-compatible endpoint (`/api/v1/responses`) — nice client-compat shim, but
A2A/MCP are the contract surfaces of this product; revisit after M4. Docling-style advanced
file parsing. External chat-memory backends (Redis/Mem0) for `data.message_history`.
Directory agent well-known card (multi-agent discovery).

### 18.3 Rejected (by design)

Multi-user/superuser (`LANGFLOW_SUPERUSER*`, `AUTO_LOGin`), projects/folders (flat + tags),
telemetry/tracing env flags (lga has **no telemetry**), Celery/redis job queues
(single-process asyncio per §2.4), vertex `/build` + `/monitor` APIs (replaced by §6.2/§6.4),
v1/v2 API split, embedded chat widget & shareable playground, store/marketplace,
`LANGFLOW_CACHE_TYPE` (compile cache is content-addressed, §5.3), **Python Interpreter /
Python REPL components** (server-side user-code execution violates §10.5; custom logic ships
as installed components), per-vendor vector store component zoo (replaced by §8b).

### 18.4 Handle geometry (canvas) [MUST]

Fixed sides so flows read left-to-right with control above and tools below:
**left** data inputs · **right** data outputs and router branches (amber) ·
**top** control-in (amber dot, router edge target) and the `toolset` output of
tool providers · **bottom** the `tools` input of agents. Tool providers
therefore visually hang below the agents they equip (dashed sky edges).

---

## Appendix A — Minimal FlowSpec (example 01, canonical fixture)
```json
{"schema_version":"2",
 "flow":{"name":"hello","slug":"hello","description":"smoke test","locked":false,
         "a2a":{"enabled":true,"description":"Replies with a scripted greeting."},
         "mcp":{"enabled":false}},
 "nodes":[
   {"id":"start","component_id":"lga.io.start","component_version":"1.0.0","config":{},"position":{"x":0,"y":0}},
   {"id":"fake_llm_1","component_id":"lga.testing.fake_llm","component_version":"1.0.0",
    "config":{"replies":["Hello from LGA!"]},"position":{"x":300,"y":0}},
   {"id":"end","component_id":"lga.io.end","component_version":"1.0.0","config":{},"position":{"x":600,"y":0}}],
 "edges":[
   {"id":"e1","kind":"data","source":{"node":"start","output":"message"},"target":{"node":"fake_llm_1","input":"input"}},
   {"id":"e2","kind":"data","source":{"node":"fake_llm_1","output":"message"},"target":{"node":"end","input":"message"}}]}
```

## Appendix B — A2A input-required exchange (normative shape)
```
→ message/send {message:{role:user,parts:[{kind:text,text:"delete prod db"}],messageId:m1}}
← Task{id:t1,contextId:c1,status:{state:"working"}}
   … TaskStatusUpdateEvent{state:"input-required", final:true,
       status.message.parts:[
         {kind:"text","text":"Approve deletion of prod db?"},
         {kind:"data","data":{"kind":"approval","options":["approve","reject"],"context":{...}}}]}
→ message/send {taskId:t1, contextId:c1,
     message:{role:user,parts:[{kind:"data","data":{"decision":"reject"}}],messageId:m2}}
← Task{id:t1,status:{state:"working"}} … {state:"completed",
     artifacts:[{name:"response",parts:[{kind:"text","text":"Aborted. Nothing was deleted."}]}]}
```

## Appendix C — Design tokens (`frontend/src/theme.css`, normative) [MUST]

Single source for §11.1; consumed by Tailwind v4 `@theme`. No other file may define colors.

```css
@import "tailwindcss";
@import "@fontsource-variable/instrument-sans";
@import "@fontsource-variable/jetbrains-mono";

@theme {
  --font-sans: "Instrument Sans Variable", system-ui, sans-serif;
  --font-mono: "JetBrains Mono Variable", ui-monospace, monospace;

  /* chrome */
  --color-canvas: #0E1116;
  --color-surface-1: #151A21;
  --color-surface-2: #1C232D;
  --color-surface-3: #232C38;
  --color-border: #2A3340;
  --color-border-strong: #3A4553;
  --color-text-1: #E8ECF2;
  --color-text-2: #9AA4B2;
  --color-text-3: #6B7482;
  --color-accent: #8B7CF7;
  --color-success: #4ADE80;
  --color-warning: #FBBF24;
  --color-danger: #F87171;

  /* port families (§11.1) */
  --color-port-message: #818CF8;
  --color-port-data: #94A3B8;
  --color-port-table: #2DD4BF;
  --color-port-documents: #34D399;
  --color-port-embedding: #A78BFA;
  --color-port-model: #22D3EE;
  --color-port-vectorstore: #E879F9;
  --color-port-toolset: #38BDF8;
  --color-port-route: #FBBF24;
  --color-port-file: #FB923C;
  --color-port-any: #6B7482;

  /* geometry */
  --radius-node: 12px;
  --radius-panel: 10px;
  --radius-input: 8px;
  --radius-chip: 6px;

  /* motion */
  --ease-standard: cubic-bezier(0.2, 0, 0, 1);
  --duration-micro: 120ms;
  --duration-panel: 200ms;
}
```

*End of spec.*