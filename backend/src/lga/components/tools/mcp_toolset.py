"""MCP Toolset — external MCP server as a tool source (SPEC §8.3)."""

from __future__ import annotations

import os
from typing import Any

from lga.sdk import Component, Output, fields, ports
from lga.sdk.component import NodeConfig
from lga.sdk.ports import LazyToolset, ToolDef


def _connection_from_config(config: dict[str, Any]) -> dict[str, Any]:
    transport = str(config.get("transport") or "streamable_http")
    if transport in ("streamable_http", "sse"):
        conn: dict[str, Any] = {"transport": transport, "url": str(config.get("url") or "")}
        headers = dict(config.get("headers") or {})
        if config.get("header_forwarding"):
            # forward inbound credentials when running server-side (Langflow parity)
            for env_key, header in (("LGA_FWD_API_KEY", "X-API-Key"),):
                if os.environ.get(env_key):
                    headers.setdefault(header, os.environ[env_key])
        if headers:
            conn["headers"] = headers
        return conn
    conn = {
        "transport": "stdio",
        "command": str(config.get("command") or ""),
        "args": list(config.get("args") or []),
    }
    if config.get("env"):
        conn["env"] = dict(config["env"])
    return conn


async def load_mcp_tools(config: dict[str, Any]) -> list[ToolDef]:
    """Live tool listing (also used by on_field_change refresh)."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient({"toolset": _connection_from_config(config)})
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


class MCPToolset(Component):
    component_id = "lga.tools.mcp_toolset"
    display_name = "MCP Toolset"
    description = "Attach the tools of an external MCP server to an agent (dashed tool edge)."
    icon = "plug"
    category = "tools"

    inputs = [
        fields.DropdownInput(
            name="server",
            display_name="Server",
            info="Globally managed MCP server (Settings → MCP Servers), or configure below.",
            options_source="mcp_servers",
            combobox=True,
        ),
        fields.TabInput(
            name="transport",
            display_name="Transport",
            options=["streamable_http", "sse", "stdio"],
            default="streamable_http",
            info="stdio spawns a subprocess — unavailable on Windows (selector loop).",
        ),
        fields.StrInput(name="url", display_name="URL", placeholder="http://localhost:9000/mcp"),
        fields.DictInput(name="headers", display_name="Headers", advanced=True),
        fields.StrInput(name="command", display_name="Command", advanced=True),
        fields.NestedDictInput(
            name="args",
            display_name="Args",
            schema={"type": "array", "items": {"type": "string"}},
            advanced=True,
        ),
        fields.DictInput(name="env", display_name="Env", advanced=True),
        fields.MultiselectInput(
            name="tools",
            display_name="Tools",
            info="Allowlist; empty = all tools. Refresh lists live from the server.",
            options_source="mcp_tools",
            refresh_button=True,
        ),
        fields.BoolInput(
            name="header_forwarding",
            display_name="Forward Auth Headers",
            default=False,
            advanced=True,
        ),
        fields.FloatInput(
            name="timeout_s", display_name="Timeout (s)", default=30.0, advanced=True
        ),
    ]
    outputs = [Output(name="toolset", display_name="Toolset", port=ports.TOOLSET)]

    def provide_tools(self, ctx) -> LazyToolset:
        config = dict(ctx.config)
        return LazyToolset(lambda: load_mcp_tools(config))

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            # pure tool providers never run as graph nodes; defensive no-op
            return {}

        return node

    def on_field_change(self, config: NodeConfig, field_name: str, value: Any) -> NodeConfig:
        config = dict(config)
        config[field_name] = value
        return config

    async def health_check(self, ctx) -> None:
        await load_mcp_tools(dict(ctx.config))
