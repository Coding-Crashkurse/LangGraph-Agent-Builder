# LangGraph Agent Builder

> Design-time low-code builder for the **agentplane** platform: compose flows
> on a canvas, validate them with the platform's shared rules, and publish
> them to the agentplane runtime — served as **A2A agents** or **MCP tools**
> behind the gateway.

![license](https://img.shields.io/badge/license-MIT-green.svg)
![python](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![contract](https://img.shields.io/badge/contract-agentplane%20FlowDefinition-8A2BE2.svg)

The builder is one of several producers of agentplane **FlowDefinitions** —
CLI, hand-written YAML, and AI-generated files are equal citizens. It hosts
nothing itself: no A2A endpoints, no MCP servers, no execution. Publishing
deploys to the runtime; the playground chats with an ephemeral draft deploy
through the gateway. Stop the builder and every published flow keeps working.

```
frontend (React Flow) ──► builder backend ──► agentplane runtime API (via gateway)
                              │                      ├── POST /definitions/validate
                              │                      ├── POST /definitions + /deploy
                              │                      └── GET  /resources
                              └── agentplane-core (pinned): FlowDefinition,
                                  validate_structure(), node config models
```

## What that means in the UI

| Button | Behavior |
|---|---|
| Save | builder-local draft (with canvas layout); no platform interaction |
| Validate | local `validate_structure` instantly + runtime check when reachable; issues merged, marked `local`/`runtime` |
| Publish | runtime draft update + deploy → endpoint URL (+ registry link) |
| Playground | ephemeral deploy; built-in chat talks A2A to `/a2a/_draft/{name}` |
| Share | canonical FlowDefinition YAML — importable here, deployable via `agentplane deploy`, git-safe |

## Repo layout

```
backend/    # FastAPI design-time API (Python ≥3.12, uv) — drafts, validation,
            # publish/playground, resources proxy; agentplane wheels in vendor/
frontend/   # React + React Flow canvas; panels render from GET /node-types
examples/   # canonical FlowDefinition YAML files (round-trip + contract tested)
schemas/    # pinned flow-definition.schema.json from the targeted agentplane release
```

## Quickstart

```bash
# backend
cd backend && uv sync && uv run lab serve      # http://127.0.0.1:8000
# frontend dev server (proxies /api to the backend)
cd frontend && pnpm install && pnpm dev        # http://localhost:5173
```

Point the builder at a platform with `BUILDER_RUNTIME_URL=<gateway URL>`
(plus OIDC settings for the shared realm — see `backend/README.md`). Without
a runtime the builder still works fully offline: edit, validate locally,
export/import canonical YAML.

## Checks

```bash
cd backend && uv run pytest && uv run ruff check && uv run mypy
cd frontend && pnpm test && pnpm lint && npx tsc -b
```

MIT — a learning project. Platform contracts live in the
[agentplane](https://github.com/Coding-Crashkurse/agentplane) repo.
