# langgraph-agent-builder

> Distribution name: **`langgraph-agent-builder`**. CLI command: **`lab`**.
> Python import package: **`langgraph_agent_builder`**.

Design-time low-code flow builder for the [agentplane](https://github.com/Coding-Crashkurse/agentplane)
platform. Compose flows on a canvas, validate them with the shared
`agentplane-core` rules, and publish them to the agentplane runtime — which
serves each flow as an A2A agent or MCP tool behind the gateway. The builder
itself hosts nothing: no endpoints, no execution. When the builder process
stops, every published flow keeps working.

```bash
cd backend && uv sync
uv run lab serve        # design-time API + bundled frontend
```

- **FlowDefinition is the format.** Drafts, exports and imports are canonical
  FlowDefinition YAML/JSON (deterministic order, canvas positions confined to
  the `layout` block). Files are git-safe: resources by name, never secrets.
- **Types come from the platform.** `FlowDefinition`, node config models,
  `ValidationIssue` and `validate_structure()` are imported from
  `agentplane-core`/`agentplane-sdk`, pinned exactly from PyPI — the builder
  defines zero contract types of its own.
- **Validate** merges instant local checks with the runtime's authoritative
  answer (`POST /definitions/validate`), each issue marked `local`/`runtime`.
- **Publish** = update the runtime draft + deploy (returns the endpoint URL;
  registration happens platform-side). **Playground** = ephemeral deploy; the
  chat panel talks A2A to `/a2a/_draft/{name}` through the gateway.

## Configuration (env prefix `BUILDER_`)

| Variable | Default | Purpose |
|---|---|---|
| `BUILDER_RUNTIME_URL` | — | agentplane runtime API base (always a gateway URL) |
| `BUILDER_RUNTIME_TOKEN` | — | static bearer for dev setups without OIDC |
| `BUILDER_AUTH_MODE` | `none` | `none` \| `oidc` (validate JWTs, forward the user token) |
| `BUILDER_OIDC_ISSUER` / `_AUDIENCE` / `_CLIENT_ID` | — | shared Keycloak realm |
| `BUILDER_RESOURCES_UI_URL` / `_REGISTRY_UI_URL` | — | links into the platform UI |
| `BUILDER_DATABASE_URL` | SQLite under `~/.langgraph-agent-builder` | draft storage |

## Development

```bash
uv run pytest && uv run ruff format . && uv run ruff check --fix . && uv run mypy
```

The platform contract is the exact PyPI pin in `pyproject.toml` plus
`../schemas/flow-definition.schema.json`; upgrading it is a deliberate PR
(bump the pin, refresh the schema) gated by the round-trip and contract tests.
