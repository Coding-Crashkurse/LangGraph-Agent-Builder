# CLAUDE.md — lga

**`SPEC.md` is the authoritative specification** for this repository (product,
architecture, protocols, normative identifiers/error codes). This file only
adds working conventions and machine-specific constraints. When SPEC.md and
reality drift, fix the code or amend SPEC.md in the same change — never let
them diverge silently.

> History: the repo previously hosted the "GraphForge" PoC (see the baseline
> commit). It was rewritten against SPEC.md as the `lga` package; the old
> CLAUDE.md describing GraphForge is obsolete.

## What lives where

```
backend/src/lga/
  sdk/         Component SDK: fields (§4.2), ports+coercions (§4.3), registry, harness
  schema/      FlowSpec (§5.2), FlowState (§5.1), diagnostics codes (§5.4), events (§6.2)
  compiler/    P1 parse → P2 resolve → P3 validate → P4 wire → P5 emit; export_python
  runtime/     executor (cancel/interrupts/debug-step/RT codes), checkpointer factory, event bus
  a2a/         card, DB task store + state machine, executor bridge, push (SSRF), mounts, handler
  mcp/         flows-as-tools server (/mcp)
  api/         Studio REST /api/v1
  services/    settings (LGA_*), secrets (Fernet), api keys, files, flows, runs, orchestrator
  components/  built-in catalog v1 (§12) — one module per component family
  cli/         typer app: run/init/migrate/flow/component/apikey/config/version
  db/          SQLAlchemy models + alembic (ships inside the wheel)
backend/tests/ unit, compiler goldens, executor, tests/a2a (compliance = "A2A erfüllt"), mcp, cli
frontend/      React Studio; TS types generated from OpenAPI (pnpm gen:api)
examples/      01–10, all runnable; run via `uv run pytest ../examples` from backend/
```

## Commands

```bash
cd backend
uv sync
uv run lga run --port 8010          # THE entry point (see Windows note below)
uv run pytest                       # full backend suite (SQLite tier; +Postgres when :55432 up)
uv run pytest --cov=lga             # + coverage gate (fail_under = 85, REFACTOR.md §4)
uv run mypy                         # strict type-checker gate (REFACTOR.md §2/§8)
uv run ruff check --fix && uv run ruff format

cd frontend
pnpm dev                            # :5173 → proxies to :8010
pnpm lint && pnpm test && pnpm build
pnpm gen:api                        # after changing API shapes: regen schema.gen.ts
```

Quality gates before every commit: ruff clean, **`uv run mypy` (strict) clean**,
backend pytest green with **coverage ≥ 85 %**, frontend lint+test+build green,
`uv run pytest ../examples` green. Refactor standards (typing, DI-via-Protocol,
error hierarchy, fakes-over-mocks tests) live in `REFACTOR.md` — its §0.0 records
the binding decisions (package stays `lga`, no rename; Langflow-builder
architecture stays; mypy strict; 85 % coverage).

## Machine constraints (this dev box)

1. **Ports:** 5432 and 8000 are permanently taken by other projects. Postgres
   runs on **55432** (docker compose), the backend on **8010**.
2. **Windows event loop:** psycopg async cannot run on the Proactor loop and
   uvicorn ≥0.36 forces it. `lga run` (non-reload) therefore drives uvicorn on
   its own selector loop; `--reload`/workers subprocesses are fine. Bare
   `uvicorn lga.app:app` on Windows will break the Postgres tier. stdio MCP
   toolsets do not work on Windows — use streamable_http.
3. **a2a-sdk pinned `>=0.3,<0.4`:** SPEC §7 targets protocol v0.3.x. a2a-sdk
   1.x is a rewritten server API (protocol v1.0); bumping is a deliberate
   migration, not a routine update. Known sdk quirks we work around:
   consumer `close(immediate=True)` wipes tapped child queues (hence the
   cancel-event ordering in `a2a/executor.py` and the non-awaiting
   `Executor.cancel`), and resubscribe has no replay (hence `a2a/handler.py`).
4. **pnpm 11** blocks postinstall scripts; esbuild is allowed via
   `frontend/pnpm-workspace.yaml` (`allowBuilds`).

## Conventions & guardrails

- Never hand-roll A2A/MCP protocol types — import from `a2a.types` / `mcp`.
  Our wire formats live in `lga/schema/`.
- Never put executable code into FlowSpec JSON; components are installed
  classes (entry point `lga.components` or `LGA_COMPONENTS_PATH`). No
  eval/exec of user input, sandboxed jinja only (§10.5).
- All runs go through `runtime/executor.py` (playground/api/debug/a2a/mcp
  share it — A2A translates via the `event_sink` hook). No third path.
- Diagnostics codes, RT error codes, JSON field names are normative — copy
  from SPEC.md verbatim; tests in `tests/test_compiler.py` and `tests/a2a/`
  pin them.
- `lga.sdk` must not import FastAPI/SQLAlchemy (import-linter contract).
- component_id is immutable; breaking changes ⇒ new id + `legacy=True` (§4.9).
- SSE, not WebSockets. SQLite default, Postgres tier — never Redis.
- Adding a component must never require frontend changes; if it seems to, the
  FieldWidgetRegistry is missing a §4.2 widget — fix it there.
