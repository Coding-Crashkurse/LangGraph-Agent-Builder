"""Tiny FastMCP demo server the flow's MCP Toolset connects to.

Usage: python demo_server.py [port]   (default 9007; endpoint /mcp)
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-tools", stateless_http=True, streamable_http_path="/mcp")


@mcp.tool()
def lookup_order(order_id: str) -> str:
    """Look up an order by id (demo data)."""
    orders = {"1001": "shipped 2026-07-01", "1002": "processing"}
    return orders.get(order_id, f"order {order_id} not found")


@mcp.tool()
def shipping_estimate(country: str) -> str:
    """Estimate shipping days for a country (demo data)."""
    return {"de": "2 days", "us": "5 days"}.get(country.lower(), "7-10 days")


if __name__ == "__main__":
    import uvicorn

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9007
    uvicorn.run(mcp.streamable_http_app(), host="127.0.0.1", port=port)
