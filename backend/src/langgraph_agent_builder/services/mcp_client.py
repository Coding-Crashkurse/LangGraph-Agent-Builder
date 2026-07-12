"""External MCP server client helpers (SPEC §8.3).

Used by the ``mcp_server`` resource health probe and any live tool listing.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, cast

from langgraph_agent_builder.sdk.ports import ToolDef


def _connection_from_config(config: dict[str, Any]) -> dict[str, Any]:
    transport = str(config.get("transport") or "streamable_http")
    timeout = float(config.get("timeout_s") or 0)
    if transport in ("streamable_http", "sse"):
        conn: dict[str, Any] = {"transport": transport, "url": str(config.get("url") or "")}
        headers = dict(config.get("headers") or {})
        if config.get("header_forwarding"):
            # forward inbound credentials when running server-side (Langflow parity)
            for env_key, header in (("LAB_FWD_API_KEY", "X-API-Key"),):
                if os.environ.get(env_key):
                    headers.setdefault(header, os.environ[env_key])
        if headers:
            conn["headers"] = headers
        if timeout > 0:
            conn["timeout"] = timeout
    else:
        conn = {
            "transport": "stdio",
            "command": str(config.get("command") or ""),
            "args": list(config.get("args") or []),
        }
        if config.get("env"):
            conn["env"] = dict(config["env"])
    if timeout > 0:
        # per-request read timeout on the MCP ClientSession (all transports)
        conn["session_kwargs"] = {"read_timeout_seconds": timedelta(seconds=timeout)}
    return conn


async def load_mcp_tools(config: dict[str, Any]) -> list[ToolDef]:
    """Live tool listing (also used by the mcp_server resource health probe)."""
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.sessions import Connection

    client = MultiServerMCPClient({"toolset": cast(Connection, _connection_from_config(config))})
    tools = await client.get_tools()
    allow = set(config.get("tools") or [])
    defs: list[ToolDef] = []
    for tool in tools:
        if allow and tool.name not in allow:
            continue
        defs.append(
            ToolDef(
                name=tool.name,
                description=tool.description or "",
                args_schema=getattr(tool, "args", {}) or {},
                callable_ref=tool,  # already a LangChain BaseTool
            )
        )
    return defs
