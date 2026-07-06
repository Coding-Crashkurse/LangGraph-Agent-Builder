# 08 · flow_as_mcp_tool

Publish a flow with `mcp.enabled` and it appears as a tool named `ask_library`
at `http://127.0.0.1:8000/mcp` (streamable HTTP; SSE fallback at `/mcp/sse`).

This CI variant uses a Fake LLM; for the real RAG version publish example 03
with the same `mcp` block.

**Claude Code / Cursor config** (also served at `GET /api/v1/mcp/config`):

```json
{
  "mcpServers": {
    "lga": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "X-API-Key": "<lga_sk_… with mcp:invoke scope, if auth is on>" }
    }
  }
}
```

Interrupt policy (§8.1): flows containing Human Approval/Input are rejected
from MCP exposure (E063) unless `mcp.auto_resolve_interrupts` is set — MCP has
no input-required concept; use the A2A endpoint for approval-style flows.
