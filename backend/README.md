# langgraph-agent-builder

> Distribution name: **`langgraph-agent-builder`**. CLI command: **`lab`**
> (alias `langgraph-agent-builder`). Python import package: **`langgraph_agent_builder`**.

LangGraph-native visual agent builder — compose agent flows on a canvas, compile
them to real LangGraph `StateGraph`s, and serve every published flow as an
A2A agent and/or MCP tool.

```bash
uv tool install langgraph-agent-builder   # or: pip install langgraph-agent-builder
lab run                                    # zero-config: SQLite, bundled frontend, opens browser
```

- **Zero config:** `lab run` starts on SQLite under `~/.langgraph-agent-builder`; switch to Postgres by
  setting `LAB_DATABASE_URL=postgresql+asyncpg://…`.
- **A2A:** each published flow is a spec-compliant A2A agent at `/a2a/{slug}`
  (agent card, streaming, tasks, push notifications, input-required ⇄ LangGraph interrupts).
- **MCP:** published flows are MCP tools at `/mcp` (streamable HTTP).
- **SDK:** ship custom components as installed Python packages via the
  `langgraph_agent_builder.components` entry point — no string-eval, ever.

Extras (install as `langgraph-agent-builder[<name>]`): `openai`, `anthropic`, `ollama`,
`postgres`, `pgvector`, `qdrant`, `weaviate`, `chroma`, `all`.

See the [GitHub repository](https://github.com/Coding-Crashkurse/LangGraph-Agent-Builder)
for documentation and examples.
