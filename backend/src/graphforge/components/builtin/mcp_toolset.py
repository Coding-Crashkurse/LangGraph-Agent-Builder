"""External MCP server as a tool source for agent nodes (attach edges)."""

from typing import Any, Literal

from pydantic import Field, model_validator

from graphforge.components.base import ComponentConfig, ToolProviderComponent
from graphforge.components.registry import register


class MCPToolsetConfig(ComponentConfig):
    transport: Literal["streamable_http", "stdio"] = Field(
        "streamable_http",
        description="stdio spawns a subprocess — not supported on the Windows dev setup "
        "(selector event loop); prefer streamable_http.",
    )
    url: str = Field("", description="MCP endpoint URL (streamable_http).")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers.")
    command: str = Field("", description="Executable (stdio).")
    args: list[str] = Field(default_factory=list, description="Arguments (stdio).")
    env: dict[str, str] = Field(default_factory=dict, description="Environment (stdio).")
    tool_allowlist: list[str] = Field(
        default_factory=list, description="If set, only these tool names are exposed."
    )

    @model_validator(mode="after")
    def _check_transport_fields(self) -> "MCPToolsetConfig":
        if self.transport == "streamable_http" and not self.url:
            raise ValueError("url is required for streamable_http transport")
        if self.transport == "stdio" and not self.command:
            raise ValueError("command is required for stdio transport")
        return self


@register
class MCPToolset(ToolProviderComponent):
    name = "mcp_toolset"
    display_name = "MCP Toolset"
    description = "Attach the tools of an external MCP server to an agent node."
    category = "tools"
    version = 1
    config_model = MCPToolsetConfig
    attachment_kind = "tools"

    async def get_tools(self, config: MCPToolsetConfig) -> list[Any]:
        # Imported lazily: adapters pull in the whole mcp client stack.
        from langchain_mcp_adapters.client import MultiServerMCPClient

        connection: dict[str, Any]
        if config.transport == "streamable_http":
            connection = {"transport": "streamable_http", "url": config.url}
            if config.headers:
                connection["headers"] = dict(config.headers)
        else:
            connection = {
                "transport": "stdio",
                "command": config.command,
                "args": list(config.args),
            }
            if config.env:
                connection["env"] = dict(config.env)

        client = MultiServerMCPClient({"toolset": connection})
        tools = await client.get_tools()
        if config.tool_allowlist:
            allowed = set(config.tool_allowlist)
            tools = [tool for tool in tools if tool.name in allowed]
        return tools
