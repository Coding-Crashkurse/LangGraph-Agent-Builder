# lga

LangGraph-native visual agent builder — compose agent flows on a canvas, compile
them to real LangGraph `StateGraph`s, and serve every published flow as an
A2A agent and/or MCP tool.

```bash
uv tool install lga        # or: pip install lga
lga run                    # zero-config: SQLite, bundled frontend, opens browser
```

- **Zero config:** `lga run` starts on SQLite under `~/.lga`; switch to Postgres by
  setting `LGA_DATABASE_URL=postgresql+asyncpg://…`.
- **A2A:** each published flow is a spec-compliant A2A agent at `/a2a/{slug}`
  (agent card, streaming, tasks, push notifications, input-required ⇄ LangGraph interrupts).
- **MCP:** published flows are MCP tools at `/mcp` (streamable HTTP).
- **SDK:** ship custom components as installed Python packages via the
  `lga.components` entry point — no string-eval, ever.

Extras: `lga[openai]`, `lga[anthropic]`, `lga[ollama]`, `lga[postgres]`, `lga[pgvector]`, `lga[all]`.

See `SPEC.md` in the repository for the full specification.
