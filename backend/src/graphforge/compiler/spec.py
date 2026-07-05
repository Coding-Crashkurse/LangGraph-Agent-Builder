"""Pydantic models for the Flow JSON — the source of truth (CLAUDE.md §7).
The frontend mirrors these in frontend/src/api/types.ts."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

START_NODE = "__start__"
END_NODE = "__end__"


class Position(BaseModel):
    """Canvas-only; the compiler ignores it."""

    x: float = 0.0
    y: float = 0.0


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    component: str
    component_version: int = 1
    config: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)


class EdgeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["control", "attach"] = "control"
    source: str
    source_handle: str | None = None
    target: str


class AgentSkillSpec(BaseModel):
    id: str = "skill"
    name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class AgentCardSpec(BaseModel):
    """User-editable subset; url/version/capabilities/transports are derived (§9.3)."""

    name: str = ""
    description: str = ""
    skills: list[AgentSkillSpec] = Field(default_factory=list)
    default_input_modes: list[str] = Field(default_factory=lambda: ["text/plain"])
    default_output_modes: list[str] = Field(default_factory=lambda: ["text/plain"])
    provider_organization: str = ""
    provider_url: str = ""


class MCPToolSpec(BaseModel):
    name: str = Field("run", pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    description: str = "Run this flow."


class PublishSpec(BaseModel):
    a2a: bool = True
    mcp: bool = False
    agent_card: AgentCardSpec = Field(default_factory=AgentCardSpec)
    mcp_tool: MCPToolSpec = Field(default_factory=MCPToolSpec)


class FlowSpec(BaseModel):
    id: str | None = None
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str
    description: str = ""
    version: int = 1
    nodes: list[NodeSpec] = Field(default_factory=list)
    edges: list[EdgeSpec] = Field(default_factory=list)
    publish: PublishSpec = Field(default_factory=PublishSpec)


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"] = "error"
    code: str
    message: str
    node_id: str | None = None
    edge_index: int | None = None
