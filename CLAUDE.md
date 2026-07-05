# CLAUDE.md — GraphForge (working title)

Visual builder for **LangGraph** agent workflows. Flows are designed on a React-Flow
canvas, compiled to a `StateGraph` at runtime, and published as **A2A servers**
(Agent2Agent protocol) and/or **MCP servers** — with persistent tasks, optional
custom-event streaming, human-in-the-loop, and a live debug dashboard.

This file is the single source of truth for architecture and conventions.
When in doubt, follow this document. If a decision here turns out to be wrong,
update this file in the same PR that changes the behavior.

---

## 1. What we are building (PoC scope)

A user can:

1. Compose a graph on a canvas from a **palette of components** (no user code in the UI).
2. Configure each node via an auto-generated form (from the component's Pydantic schema).
3. Define **conditional routing** (router nodes with multiple labeled outputs) and **cycles**.
4. Attach **MCP toolsets** (external MCP servers) to agent nodes.
5. Build a simple **RAG agent** (pgvector retriever + LLM agent + human approval).
6. Fill in **Agent Card metadata** (name, description, skills, capabilities).
7. **Publish** the flow as:
   - an **A2A server** (JSON-RPC primary, REST secondary, gRPC = stretch), and/or
   - an **MCP server** (Streamable HTTP, one tool per flow).
8. Watch executions in a **debug UI**: task list, status, live event stream (SSE),
   message history, node-level progress on the graph, and an input box to answer
   `input-required` tasks (human-in-the-loop).

### Non-goals (PoC)

- No auth/multi-tenancy (single-user, trusted network).
- No user-authored code in the UI. Extensibility = drop a Python component file into a folder.
- No horizontal scaling (single process; see §12 for the seams we keep clean anyway).
- No LangSmith / LangGraph Platform dependency. We deliberately self-host:
  plain `langgraph` + `a2a-sdk` + `mcp` + FastAPI.
- No flow version history UI (we bump a version int; history = stretch).

---

## 2. Architecture overview

```
┌────────────────────────────  Frontend (Vite/React/TS)  ───────────────────────────┐
│  Builder (React Flow canvas, schema-driven config forms, Agent Card editor)       │
│  Debug dashboard (tasks, live SSE event tail, HITL input, graph replay)           │
└──────────────────────────────────────┬─────────────────────────────────────────────┘
                                       │ REST + SSE
┌──────────────────────────────────────▼─────────────────────────────────────────────┐
│                          Backend — single FastAPI process                          │
│                                                                                    │
│  /api/…            Builder & debug API (flows, components, tasks, events)          │
│  /serve/a2a/{slug} A2AStarletteApplication  ── LangGraphAgentExecutor ─┐           │
│  /serve/mcp/{slug} FastMCP (streamable HTTP) ─ one tool per flow ──────┤           │
│                                                                        ▼           │
│  Component Registry ──► Flow Compiler ──► compiled StateGraph (per published flow) │
│  Event Bus (in-proc pub/sub, persisted to task_events)                             │
└───────────────┬───────────────────────────────┬────────────────────────────────────┘
                │                               │
        ┌───────▼───────┐               ┌───────▼────────┐
        │   Postgres    │               │ External MCP   │
        │  (one DB):    │               │ servers (tools │
        │  checkpoints, │               │ for agents)    │
        │  a2a tasks,   │               └────────────────┘
        │  flows,       │
        │  task_events, │
        │  pgvector     │
        └───────────────┘
```

**Key runtime idea:** publishing a flow = compiling its graph and **mounting** an
A2A sub-app and/or MCP sub-app into the running FastAPI app under `/serve/…`.
On startup, all published flows are re-mounted. No codegen, no subprocesses.

---

## 3. Repository layout

```
.
├── CLAUDE.md
├── docker-compose.yml            # postgres (pgvector/pgvector image)
├── backend/
│   ├── pyproject.toml            # managed with uv
│   ├── alembic/                  # migrations for OUR tables only (see §11)
│   └── src/graphforge/
│       ├── components/
│       │   ├── base.py           # BaseComponent, RouterComponent, ToolProviderComponent
│       │   ├── registry.py       # discovery + registry + /api/components payload
│       │   ├── builtin/          # shipped palette (one file per component)
│       │   └── user/             # drop-in folder for project-specific components
│       ├── compiler/
│       │   ├── spec.py           # Pydantic models for the Flow JSON (source of truth)
│       │   └── build.py          # FlowSpec -> compiled StateGraph
│       ├── runtime/
│       │   ├── state.py          # FlowState schema + reducers
│       │   ├── events.py         # EventBus, event types, persistence hook
│       │   └── manager.py        # FlowRuntimeManager: compile/mount/unmount published flows
│       ├── a2a/
│       │   ├── executor.py       # LangGraphAgentExecutor (the A2A<->LangGraph bridge)
│       │   ├── server.py         # build A2AStarletteApplication for a flow
│       │   └── card.py           # AgentCard assembly from flow metadata
│       ├── mcp_server/
│       │   └── server.py         # FastMCP app factory for a flow
│       ├── rag/
│       │   └── ingest.py         # ingestion helpers for pgvector collections
│       ├── api/
│       │   ├── app.py            # FastAPI app factory, lifespan (db pools, remounts)
│       │   ├── flows.py          # CRUD, validate, publish
│       │   ├── components.py     # palette endpoint
│       │   ├── debug.py          # tasks, events (SSE), HITL input, cancel
│       │   └── collections.py    # RAG ingestion endpoints
│       ├── db/                   # engine, sessions, SQLAlchemy models
│       └── settings.py           # pydantic-settings; env-driven
├── frontend/
│   ├── package.json              # pnpm
│   └── src/
│       ├── api/                  # typed client + SSE helpers
│       ├── builder/              # canvas, palette, config panel, agent card editor
│       ├── debug/                # dashboard
│       ├── components/ui/        # shadcn/ui
│       └── lib/
└── examples/
    └── flows/library_rag.json    # seeded demo flow (see §16)
```

---

## 4. Tech stack (pinned intentions, not exact versions)

Backend (Python ≥ 3.12, managed with **uv**):

| Concern            | Library                                              |
|--------------------|------------------------------------------------------|
| HTTP server        | `fastapi`, `uvicorn[standard]`                       |
| Orchestration      | `langgraph`, `langchain-core`                        |
| LLMs               | `langchain` `init_chat_model` (provider-agnostic, model strings like `openai:gpt-4o-mini`) |
| Checkpointing      | `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`) |
| A2A                | `a2a-sdk[http-server,sql]` **pinned `>=0.3,<0.4`** (Starlette apps, `DatabaseTaskStore`). a2a-sdk 1.x = protocol v1.0 with a rewritten server API; §9 is written against 0.3 — migrating is a deliberate follow-up, not a routine bump. |
| MCP (server+client)| `mcp` (FastMCP), `langchain-mcp-adapters` (`MultiServerMCPClient`) |
| RAG                | `langchain-postgres` (PGVector), pgvector extension  |
| DB                 | `sqlalchemy[asyncio]`, `asyncpg`, `alembic`          |
| Config             | `pydantic` v2, `pydantic-settings`                   |
| Quality            | `ruff` (lint+format), `pytest`, `pytest-asyncio`, `httpx` |

Frontend (Node ≥ 20, **pnpm**):

| Concern        | Library                                   |
|----------------|-------------------------------------------|
| App            | Vite + React 18 + TypeScript (strict)     |
| Canvas         | `@xyflow/react`                           |
| State          | `zustand` (canvas), `@tanstack/react-query` (server state) |
| Forms          | JSON-Schema-driven renderer (`@rjsf/core` + custom widgets, or a thin in-house renderer — decide once, in `frontend/src/builder/forms/`) |
| Styling        | Tailwind + shadcn/ui, `lucide-react`      |
| Live updates   | native `EventSource` (SSE). No WebSockets. |

**Rules:**
- Protocol types come from the SDKs. Never re-declare A2A or MCP protocol models by hand;
  import from `a2a.types` / `mcp`. Our own wire formats live in `compiler/spec.py` and `runtime/events.py`.
- Backend is fully async. No sync DB calls, no `requests`.

---

## 5. Core decisions (mini-ADRs)

1. **Runtime interpreter, not codegen.** Flows are JSON; the compiler builds a
   `StateGraph` in-process at publish time. Codegen export (à la `langgraph-gen`) is a stretch goal.
2. **Fixed state schema** (`FlowState`, §8) for all flows in the PoC. Components declare
   `state_reads`/`state_writes`; the compiler validates them against the schema.
   Per-flow custom state = later.
3. **No code inside flow JSON.** Flows reference components by `name` + `version` + `config`.
   (Deliberate departure from Langflow, which serializes component source into the flow.)
4. **Two edge kinds.** `control` (LangGraph edges / conditional edges) and `attach`
   (tool providers → agent nodes). `attach` edges never become graph edges.
5. **One process, dynamic mounts.** Publish = mount `/serve/a2a/{slug}` and/or `/serve/mcp/{slug}`.
6. **`contextId == thread_id`.** A2A conversation context maps 1:1 onto the LangGraph
   checkpointer thread. One A2A task = one graph run within that thread.
7. **Custom events are optional by design.** Components MAY emit progress events; the
   executor forwards them to streaming clients and always mirrors them to the debug event bus.
   Non-streaming clients (`message/send`) are unaffected.
8. **Transports:** JSON-RPC is primary and always on; REST (HTTP+JSON) is enabled via the
   SDK where cheap; gRPC is a feature-flagged stretch. The Agent Card advertises
   `preferredTransport` + `additionalInterfaces` accordingly.

---

## 6. Component system

### 6.1 Base classes (`components/base.py`)

```python
from abc import ABC, abstractmethod
from typing import Any, Callable, ClassVar
from pydantic import BaseModel

class ComponentConfig(BaseModel):
    """Base for all component configs. JSON Schema of this model drives the UI form."""

class BaseComponent(ABC):
    # --- static metadata (class-level) ---
    name: ClassVar[str]                 # unique snake_case id, e.g. "pgvector_retriever"
    display_name: ClassVar[str]
    description: ClassVar[str]
    category: ClassVar[str]             # palette grouping: "llm" | "rag" | "flow" | "tools" | "io"
    version: ClassVar[int] = 1
    config_model: ClassVar[type[ComponentConfig]]
    state_reads: ClassVar[list[str]] = []
    state_writes: ClassVar[list[str]] = []
    accepts_attachments: ClassVar[list[str]] = []   # e.g. ["tools"] on agent components

    @abstractmethod
    def build(self, config: ComponentConfig, ctx: "BuildContext") -> Callable:
        """Return an async node function: (state, config) -> partial state update.
        ctx gives access to attached tool providers, db pools, settings."""

    # Helper available to node functions via runtime/events.py:
    #   emit(event_type: str, data: dict) -> None
    # Implemented with langgraph's get_stream_writer(); safe no-op when not streaming.

class RouterComponent(BaseComponent):
    @abstractmethod
    def outputs(self, config: ComponentConfig) -> list[str]:
        """Labels of the outgoing conditional branches. The canvas renders one
        source handle per label; the compiler wires add_conditional_edges."""

class ToolProviderComponent(BaseComponent):
    attachment_kind: ClassVar[str] = "tools"
    @abstractmethod
    async def get_tools(self, config: ComponentConfig) -> list:  # list[BaseTool]
        ...
    def build(self, config, ctx):  # tool providers are not control-flow nodes
        raise NotImplementedError
```

### 6.2 Discovery & registry (`components/registry.py`)

- On startup: import every module in `components/builtin/` and `components/user/`
  (pkgutil walk). Classes register via `@register` decorator into `{name: cls}`.
- Duplicate names → hard startup error.
- `GET /api/components` returns, per component:
  `{name, display_name, description, category, version, kind: "node"|"router"|"tool_provider",
    outputs_static?, accepts_attachments, config_json_schema}`.
  The frontend builds the palette and config forms **exclusively** from this payload.
  Adding a component must never require frontend changes.
- Dev mode: `watchfiles` on the components folders triggers registry reload (best effort).

### 6.3 Built-in palette (PoC)

| name                 | kind          | purpose / config highlights |
|----------------------|---------------|------------------------------|
| `llm_agent`          | node          | Explicit tool-calling loop (deliberately **not** `create_react_agent`: we control `agent.tool_call` event emission and avoid prebuilt API drift). Config: `model`, `system_prompt`, `use_documents: bool` (inject `state["documents"]` into the prompt), temperature. `accepts_attachments=["tools"]`. Reads `messages`(+`documents`), writes `messages`. Emits `agent.tool_call` custom events per tool invocation. |
| `llm_call`           | node          | Single completion, no tools. Config: `model`, `prompt_template` (Jinja-lite over state keys), `output_key` (`messages` or `data.<key>`). |
| `pgvector_retriever` | node          | Config: `collection`, `top_k`, optional `query_from` (default: last human message). Writes `documents`. Emits `retriever.hits` event. |
| `llm_router`         | router        | LLM classification into configured `labels: list[str]` (= `outputs`). Writes `route`. |
| `human_approval`     | router        | HITL. Calls `interrupt({...})` with configurable prompt + preview of the last message; `outputs = ["approved", "rejected"]`; maps the resume payload to a branch, optionally appends reviewer feedback to `messages`. |
| `human_input`        | node          | HITL free-text: `interrupt(prompt)`; resume value appended as `HumanMessage`. |
| `mcp_toolset`        | tool_provider | External MCP server as tool source. Config: `transport` (`streamable_http` \| `stdio`), `url`/`command+args`, headers/env, `tool_allowlist`. Uses `MultiServerMCPClient`; connections cached per published flow, closed on unmount. |
| `set_data`           | node          | Write literals/templated values into `data` (glue/debugging). |

RAG ingestion is **not** a flow component in the PoC: `POST /api/collections/{name}/documents`
(accepts raw text or file upload, chunks with a simple recursive splitter, embeds via
configured embedding model) plus `uv run graphforge ingest <collection> <path>` CLI.

---

## 7. Flow spec (`compiler/spec.py`)

Pydantic models are the source of truth; frontend mirrors them in TS (`frontend/src/api/types.ts`).

```jsonc
{
  "id": "uuid",
  "slug": "library-rag",              // url-safe, unique; used in /serve/... mounts
  "name": "Library RAG Agent",
  "description": "Answers questions about the library corpus.",
  "version": 3,                        // int, bumped on every save
  "nodes": [
    {"id": "retrieve", "component": "pgvector_retriever", "component_version": 1,
     "config": {"collection": "library-docs", "top_k": 4},
     "position": {"x": 120, "y": 80}},                     // canvas-only, compiler ignores
    {"id": "agent",    "component": "llm_agent", "component_version": 1,
     "config": {"model": "openai:gpt-4o-mini", "system_prompt": "…", "use_documents": true},
     "position": {"x": 380, "y": 80}},
    {"id": "tools",    "component": "mcp_toolset", "component_version": 1,
     "config": {"transport": "streamable_http", "url": "http://localhost:9000/mcp"},
     "position": {"x": 380, "y": 260}},
    {"id": "review",   "component": "human_approval", "component_version": 1,
     "config": {"prompt": "Release this answer?"},
     "position": {"x": 640, "y": 80}}
  ],
  "edges": [
    {"kind": "control", "source": "__start__", "target": "retrieve"},
    {"kind": "control", "source": "retrieve",  "target": "agent"},
    {"kind": "attach",  "source": "tools",     "target": "agent"},
    {"kind": "control", "source": "agent",     "target": "review"},
    {"kind": "control", "source": "review", "source_handle": "approved", "target": "__end__"},
    {"kind": "control", "source": "review", "source_handle": "rejected", "target": "agent"}
  ],
  "publish": {
    "a2a": true,
    "mcp": true,
    "agent_card": {                    // user-editable subset; rest is derived (§9.3)
      "name": "Library RAG Agent",
      "description": "…",
      "skills": [{"id": "qa", "name": "Corpus Q&A", "description": "…",
                   "tags": ["rag"], "examples": ["Who wrote …?"]}],
      "default_input_modes": ["text/plain"],
      "default_output_modes": ["text/plain"]
    },
    "mcp_tool": {"name": "ask_library", "description": "Ask the library corpus."}
  }
}
```

### Compiler (`compiler/build.py`) — validation then build

Validation (all errors collected, returned as a list with node/edge refs for UI highlighting):
1. Component names + versions exist in the registry; configs validate against `config_model`.
2. Exactly one `__start__` edge; every node reachable from `__start__`.
3. Router nodes: outgoing control edges must carry `source_handle` ∈ `outputs(config)`,
   each output wired exactly once. Non-router nodes: at most one unlabeled outgoing control edge.
4. `attach` edges: source is a `ToolProviderComponent`, target `accepts_attachments`
   contains its `attachment_kind`.
5. `state_reads`/`state_writes` ⊆ `FlowState` keys.
6. Cycles are allowed (this is LangGraph); only unreachable nodes and dangling handles are errors.

Build:
- Instantiate components; for each node call `build(config, ctx)` where `ctx` carries the
  resolved attachments (e.g. tools from `mcp_toolset`, fetched lazily on first run).
- `add_node` per node; `add_edge` per plain control edge; per router:
  `add_conditional_edges(node, route_fn, {label: target})` where `route_fn` reads `state["route"]`.
- `graph.compile(checkpointer=AsyncPostgresSaver(...))` — checkpointer is **always** attached
  (required for `interrupt()` and for `contextId` continuity).

---

## 8. State model (`runtime/state.py`)

```python
class FlowState(MessagesState):            # messages: Annotated[list, add_messages]
    documents: list[Document]              # last-write-wins
    route: str | None                      # router scratch, last-write-wins
    data: dict[str, Any]                   # shallow-merge reducer (op: {**old, **new})
```

Fixed for the PoC (decision #2). If a use case genuinely needs more, extend `FlowState`
here — do not fork per-flow schemas yet.

---

## 9. A2A exposure

### 9.1 Server assembly (`a2a/server.py`)

Per published flow:

```python
handler = DefaultRequestHandler(
    agent_executor=LangGraphAgentExecutor(compiled_graph, flow),
    task_store=DatabaseTaskStore(engine),      # a2a-sdk[sql] on our Postgres
)
a2a_app = A2AStarletteApplication(agent_card=build_agent_card(flow), http_handler=handler)
fastapi_app.mount(f"/serve/a2a/{flow.slug}", a2a_app.build())
```

- JSON-RPC endpoint + `/.well-known/agent-card.json` come from the SDK.
- REST (HTTP+JSON): enable via the SDK's REST application variant for the same handler,
  mounted alongside, and advertised in `additionalInterfaces`. If the installed SDK version
  makes this awkward, ship JSON-RPC-only and leave a `TODO(transport-rest)`.
- gRPC: behind `settings.enable_grpc` (default off), separate port. Stretch — do not block on it.

### 9.2 The bridge: `LangGraphAgentExecutor` (`a2a/executor.py`)

This mapping table is normative:

| A2A                                   | LangGraph                                            |
|---------------------------------------|------------------------------------------------------|
| `contextId`                           | `configurable.thread_id` (Postgres checkpointer)     |
| Task (`taskId`)                       | one graph run (invoke/stream) on that thread         |
| `message/send`                        | run to completion, return final artifact             |
| `message/stream` (SSE)                | `astream(..., stream_mode=["custom","updates"])` → `TaskStatusUpdateEvent`s |
| component `emit(type, data)`          | `TaskState.working` update with a `DataPart({type, data, node})` |
| `interrupt(payload)`                  | `TaskState.input_required`, payload as message; executor returns |
| follow-up message on same task        | `Command(resume=<user input>)` on the same thread    |
| final assistant message               | Task artifact (TextPart) + `TaskState.completed`     |
| `tasks/cancel`                        | cancel the asyncio task of the run; `TaskState.canceled`; thread state stays at last checkpoint |
| unhandled exception                   | `TaskState.failed` with error message                |

Reference sketch (canonical structure; align details with the installed `a2a-sdk` and its
official LangGraph sample when implementing):

```python
class LangGraphAgentExecutor(AgentExecutor):
    def __init__(self, graph, flow): ...

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        cfg = {"configurable": {"thread_id": task.context_id}}

        snapshot = await self.graph.aget_state(cfg)
        resuming = bool(snapshot.tasks and any(t.interrupts for t in snapshot.tasks))
        graph_input = (Command(resume=context.get_user_input()) if resuming
                       else {"messages": [HumanMessage(context.get_user_input())]})

        await updater.update_status(TaskState.working)
        async for mode, chunk in self.graph.astream(graph_input, cfg,
                                                    stream_mode=["custom", "updates"]):
            if mode == "custom":
                await updater.update_status(TaskState.working,
                    message=updater.new_agent_message(parts=[Part(root=DataPart(data=chunk))]))
                bus.publish(task.id, chunk)                      # debug UI mirror
            elif mode == "updates":
                if "__interrupt__" in chunk:
                    payload = chunk["__interrupt__"][0].value
                    await updater.update_status(TaskState.input_required,
                        message=updater.new_agent_message(parts=[Part(root=DataPart(data=payload))]),
                        final=True)
                    bus.publish(task.id, {"type": "interrupt", "data": payload})
                    return
                bus.publish(task.id, {"type": "node.update", "data": summarize(chunk)})

        final_text = extract_final_text(await self.graph.aget_state(cfg))
        await updater.add_artifact([Part(root=TextPart(text=final_text))], name="response")
        await updater.complete()

    async def cancel(self, context, event_queue) -> None:
        # cancel running asyncio task via runtime manager; mark canceled
```

Notes:
- **Every** run goes through this executor, including debug-UI test runs (the debug UI is
  an A2A client, see §14). One code path, no divergence.
- Multiple tasks per `contextId` are normal (multi-turn conversation on one thread).
- The event bus mirror is what makes the debug UI work for streaming *and* non-streaming
  clients — internal events always flow, regardless of what the A2A client requested.

### 9.3 Agent Card (`a2a/card.py`)

- User-editable in the UI (publish dialog): name, description, skills (id/name/description/
  tags/examples), input/output modes, provider info.
- Derived automatically: `url` (= `{settings.base_url}/serve/a2a/{slug}`), `version`
  (= flow version), `capabilities` (`streaming=True`; `push_notifications=False` for the PoC),
  `preferred_transport` and `additional_interfaces` from enabled transports.
- Stored as `flows.agent_card` (jsonb, the editable subset only); assembled into an
  `a2a.types.AgentCard` at mount time. Validation errors surface in the publish dialog.

---

## 10. MCP exposure (`mcp_server/server.py`)

Per published flow, a `FastMCP` instance mounted at `/serve/mcp/{slug}` (Streamable HTTP):

- One tool, named/described from `publish.mcp_tool` (default: `run`).
  Signature: `(message: str, thread_id: str | None) -> str`.
  `thread_id` gives MCP callers the same conversation continuity A2A gets via `contextId`.
- Custom events → `ctx.report_progress(...)` / `ctx.info(...)` so MCP clients that render
  progress get live feedback. Events are mirrored to the debug bus identically to A2A runs.
- Optional resource `card` returning the Agent Card JSON (cheap, nice for discovery parity).
- **HITL over MCP:** default behavior is documented and enforced — if the graph interrupts,
  the tool call fails fast with an error instructing to use the A2A endpoint for
  approval-style flows. Stretch: map `interrupt` → MCP **elicitation** (`ctx.elicit`) where
  the client supports it; put behind `settings.enable_mcp_elicitation`.
- Tasks: MCP tool calls create a row in our `runs`/`task_events` log (source=`mcp`) so they
  appear in the debug UI. A2A remains the primary protocol for long-running task semantics.

---

## 11. Persistence (one Postgres, image `pgvector/pgvector:pg17`)

| Tables                        | Owner / migration                                   |
|-------------------------------|------------------------------------------------------|
| `flows`                       | ours (alembic): id, slug, name, description, version, graph jsonb, agent_card jsonb, publish flags, mcp_tool jsonb, timestamps |
| `task_events`                 | ours (alembic): id, task_id, flow_id, source (`a2a`\|`mcp`\|`system`), type, payload jsonb, created_at. Feeds SSE replay + live tail. |
| `runs` (mcp + bookkeeping)    | ours (alembic): maps non-A2A executions into the dashboard |
| a2a task store                | `a2a-sdk` `DatabaseTaskStore` — call its create/init routine on startup; **never** migrate its tables with alembic |
| langgraph checkpoints         | `AsyncPostgresSaver.setup()` on startup; not alembic-managed |
| pgvector collections          | `langchain-postgres` PGVector; not alembic-managed   |

Startup order (lifespan): engine → alembic-check → `AsyncPostgresSaver.setup()` →
task store init → registry load → remount published flows.

---

## 12. Runtime manager & event bus

`runtime/manager.py` — `FlowRuntimeManager`:
- `publish(flow)` → validate, compile, mount a2a/mcp apps, track running asyncio tasks.
- `unpublish(flow)` / `republish` on save of a published flow (unmount → recompile → mount).
- Holds MCP client connections (`mcp_toolset`) per flow; closes them on unmount.
- Tracks in-flight runs per task id → enables cancel.

`runtime/events.py` — `EventBus`:
- In-process pub/sub keyed by task id + a global firehose topic.
- Every published event is also appended to `task_events` (async, fire-and-forget queue).
- SSE endpoints subscribe: replay persisted events first (`Last-Event-ID` supported), then live.
- Single-process today; if we ever scale out, swap the fan-out to Postgres LISTEN/NOTIFY
  behind the same interface. Do not introduce Redis in the PoC.

Event envelope (ours, `runtime/events.py`):
```json
{"id": "ulid", "task_id": "…", "flow_id": "…", "source": "a2a|mcp|system",
 "type": "node.start|node.update|custom.<type>|interrupt|status|artifact|error",
 "node": "agent", "data": {…}, "ts": "iso8601"}
```

---

## 13. Builder & debug API (`/api`)

```
GET    /api/components                         # palette (§6.2)
GET    /api/flows                              # list
POST   /api/flows                              # create
GET    /api/flows/{id}
PUT    /api/flows/{id}                         # save (bumps version; republish if published)
DELETE /api/flows/{id}
POST   /api/flows/{id}/validate                # compiler validation report
POST   /api/flows/{id}/publish                 # body: {a2a, mcp, agent_card, mcp_tool}
POST   /api/flows/{id}/unpublish

GET    /api/debug/flows/{id}/tasks             # from a2a task store + runs, newest first
GET    /api/debug/tasks/{task_id}              # status, history, artifacts
GET    /api/debug/tasks/{task_id}/events       # SSE: replay + live
GET    /api/debug/flows/{id}/events            # SSE firehose per flow (dashboard live tiles)
POST   /api/debug/flows/{id}/messages          # debug UI acts as A2A client (see §14)
POST   /api/debug/tasks/{task_id}/input        # answer input-required (A2A client resume)
POST   /api/debug/tasks/{task_id}/cancel

POST   /api/collections/{name}/documents       # RAG ingestion (text or file upload)
GET    /api/collections                        # list collections + counts
```

The two `POST …/messages|input` endpoints must go through a real A2A client
(`a2a-sdk` client, against our own mounted `/serve/a2a/{slug}`) — not by calling the
graph directly. This keeps one execution path and dogfoods the protocol.

---

## 14. Frontend spec

### 14.1 Builder (`/flows/:id`)

- React Flow canvas. Node chrome by category color; router nodes render one labeled
  source handle per `outputs` entry; tool providers use a distinct handle type, and
  `attach` edges render dashed.
- Left: palette (grouped by category, searchable, drag to canvas).
  Right: config panel — form generated from `config_json_schema`; validation errors from
  `/validate` shown inline and as node badges.
- Toolbar: Save, Validate, Publish (dialog with A2A/MCP toggles, Agent Card editor with
  live card preview, MCP tool name/description), and "Open debug".
- Client-side edge guards (mirror compiler rules): no `attach` into non-accepting nodes,
  single unlabeled outgoing control edge, handles must match router outputs.

### 14.2 Debug dashboard (`/debug/:flowId`) — "pretty, but honest"

- Header: publish status, endpoint URLs (copy buttons), link to
  `/.well-known/agent-card.json`, transport badges.
- **Task list**: live-updating table (flow firehose SSE) — task id, contextId, source
  (a2a/mcp), state chip (submitted/working/input-required/completed/failed/canceled),
  started, duration. Filter by state/source.
- **Task detail** (drawer or route):
  - Status timeline + live event tail (SSE with replay; auto-scroll, pause, raw-JSON toggle).
  - Conversation view (messages in/out, artifacts).
  - **Mini graph replay**: read-only render of the flow; nodes highlight on
    `node.start`/`node.update` events; interrupted node pulses.
  - **Input-required panel**: shows the interrupt payload; for `human_approval` render
    approve/reject buttons + optional comment; for `human_input` a text box. Submits via
    `/api/debug/tasks/{id}/input`.
  - Cancel button while working.
- **Playground tab**: chat box that talks to the published A2A endpoint via the backend
  (`/messages`), toggle "streaming" (message/stream vs message/send) so both paths are
  exercisable from the UI.
- Read `/mnt/skills/public/frontend-design/SKILL.md` before building UI (applies to
  Claude Code sessions in this repo too): no default-template look; dark-mode friendly;
  state chips and event tail should feel like a purpose-built ops tool.

---

## 15. Dev environment & commands

```bash
docker compose up -d postgres          # pgvector/pgvector:pg17, host port 55432 (5432 is usually taken on dev boxes)

# backend
cd backend
uv sync
uv run alembic upgrade head                # also runs automatically in the app lifespan
uv run graphforge serve --reload           # blessed entry; sets the selector loop policy
# (POSIX only: `uv run uvicorn graphforge.api.app:app --reload --port 8000` works too.
#  On Windows, bare non-reload uvicorn uses the Proactor loop, which psycopg async
#  cannot use — `graphforge serve` handles this. Consequence: stdio MCP toolsets are
#  unavailable on Windows; use streamable_http.)

# frontend
cd frontend
pnpm install
pnpm dev                               # vite on 5173, proxies /api + /serve to :8000

# quality gates (run before every commit)
cd backend  && uv run ruff check --fix && uv run ruff format && uv run pytest
cd frontend && pnpm lint && pnpm test
```

Env (`backend/.env`, via pydantic-settings):
```
DATABASE_URL=postgresql+asyncpg://graphforge:graphforge@localhost:55432/graphforge
BASE_URL=http://localhost:8000        # used in Agent Card urls
OPENAI_API_KEY=…                      # or any provider supported by init_chat_model
EMBEDDING_MODEL=openai:text-embedding-3-small
ENABLE_GRPC=false
ENABLE_MCP_ELICITATION=false
```

---

## 16. Testing strategy

- **Compiler**: pure unit tests — valid/invalid specs, router wiring, attach rules,
  state read/write validation, cycle acceptance. This is the highest-value test surface.
- **Executor**: integration tests with a tiny deterministic flow (fake LLM component in
  `components/builtin/testing.py`, only registered when `settings.testing`):
  send → completed; stream → custom events observed; interrupt → input-required →
  resume → completed; cancel. Use the real `a2a-sdk` client against an in-process ASGI app
  (httpx ASGITransport). Postgres via testcontainers (or compose db with per-test schemas).
- **MCP**: `mcp` client session against the mounted app: tool discovery, run, progress.
- **Frontend**: vitest for spec↔TS type mapping and form renderer; no e2e in the PoC.
- **Demo flow as fixture**: `examples/flows/library_rag.json` must always validate — CI test.

---

## 17. Milestones (each ends runnable + demoable)

1. **Skeleton**: repo layout, compose, FastAPI lifespan, health check, Vite shell.
2. **Components**: base classes, registry, `/api/components`; `llm_call`, `set_data`.
3. **Compiler + state**: spec models, validation report, build; run a hardcoded flow in a test.
4. **Canvas MVP**: palette, drag/drop, schema forms, save/load/validate against API.
5. **A2A publish**: executor (send-path), `DatabaseTaskStore`, checkpointer, agent card
   editor, mount/unmount. Verify with the a2a-sdk client from a script.
6. **Streaming + HITL**: custom events end-to-end (emit → SSE → a2a stream), `human_approval`,
   `human_input`, resume path, cancel.
7. **Debug UI**: task list, detail, live tail, input panel, playground, graph replay.
8. **MCP both ways**: `mcp_toolset` provider (client) + per-flow MCP server exposure.
9. **RAG demo**: pgvector retriever, ingestion endpoint/CLI, seed `library_rag.json`.
10. **Stretch** (only after 1–9): REST transport polish, gRPC, MCP elicitation,
    codegen export, per-flow state schemas, push notifications.

### Definition of Done (PoC demo script)

1. `docker compose up`, backend + frontend running; ingest a handful of docs into `library-docs`.
2. In the builder: assemble the RAG flow (retriever → agent ⟵tools⟵ mcp_toolset → human_approval),
   fill the Agent Card, publish with A2A + MCP.
3. From an external `a2a-sdk` client script: `message/stream` a question → watch retriever/agent
   events live in the debug UI → task flips to `input-required` → approve **from the debug UI**
   → client receives the completed task with the answer artifact.
4. From an MCP client (e.g. inspector): discover the `ask_library` tool and run a
   (non-HITL) question with visible progress.

---

## 18. Conventions & guardrails (for every Claude Code session in this repo)

- **Never** put executable code or component source into flow JSON. Flows are configuration.
- **Never** hand-roll A2A/MCP protocol types, endpoints, or agent-card serving — the SDKs own those.
- New components: one file in `components/builtin/` (or `user/`), subclass, `@register`,
  pydantic config, declare reads/writes, unit test. Zero frontend changes — if a component
  seems to need frontend work, the form renderer is missing a JSON-schema feature; fix it there.
- All runs go through the A2A executor or the MCP tool — no third "internal" execution path.
- Custom events must degrade gracefully: `emit()` is a no-op without a stream writer.
- Async only in the backend; type hints everywhere; `ruff` clean before commit.
- SSE, not WebSockets. Postgres, not Redis. One process, until this file says otherwise.
- When bumping `a2a-sdk`, `langgraph`, or `mcp`: check the executor mapping table (§9.2)
  against the SDK changelog first; these APIs move fast. Update this file with any drift.
