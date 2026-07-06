# 07 · mcp_toolset_client

An agent whose tools come from an **external MCP server** via the MCP Toolset
component (SPEC §8.3). Ships `demo_server.py`, a tiny FastMCP server with two
demo tools (`lookup_order`, `shipping_estimate`).

```bash
python examples/07_mcp_toolset_client/demo_server.py &   # port 9007
lga flow run examples/07_mcp_toolset_client/flow.json --local --input "where is order 1001?"
```

Windows note: `stdio` MCP servers are unavailable on the Windows dev setup
(selector event loop, no subprocess support) — use `streamable_http`, as this
example does.
