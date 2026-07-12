"""Node catalog served by ``GET /node-types`` (SPEC §3).

Per platform node type + version: the JSON Schema of its config (generated
from the ``agentplane-core`` models — the builder defines no node types of
its own) plus UI metadata (label, icon, port definitions, widget hints). The
frontend renders config panels from these schemas; the port rules below keep
client-side connection guards identical to ``agentplane_core`` validation.
"""

from __future__ import annotations

from typing import Literal

from agentplane_core import (
    EndNodeConfig,
    JsonSchema,
    LlmCallNodeConfig,
    McpToolNodeConfig,
    PortType,
    RetrievalNodeConfig,
    StartNodeConfig,
)
from pydantic import BaseModel, ConfigDict, Field

# `{vars}` in prompts become input ports (mirror of agentplane_core.definition).
PROMPT_VAR_PATTERN = r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})"

# Port pairs connectable beyond same-type (mirror of core `ports_compatible`).
EXTRA_COMPATIBLE_PORTS: tuple[tuple[PortType, PortType], ...] = (
    ("documents", "text"),
    ("json", "text"),
    ("text", "json"),
)

DynamicInputs = Literal["prompt_vars", "arg_keys"]
DynamicOutputs = Literal["input_schema_properties", "structured_output_json"]
ResourceKindFilter = Literal["model_provider", "vector_db", "mcp_server"]


class PortDecl(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    type: PortType
    label: str = ""


class FieldUI(BaseModel):
    """Widget hint for one config field — UX metadata, never contract."""

    model_config = ConfigDict(frozen=True)

    widget: Literal[
        "text", "textarea", "prompt", "schema", "json", "switch", "number", "dict", "resource"
    ] = "text"
    label: str = ""
    help: str = ""
    placeholder: str = ""
    resource_kind: ResourceKindFilter | None = None
    advanced: bool = False
    # Optional object fields rendered behind an on/off switch: off = null,
    # on = show the editor with a starter value.
    toggleable: bool = False


class NodeTypeInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    version: int
    label: str
    icon: str
    category: str
    description: str
    config_schema: JsonSchema
    inputs: list[PortDecl] = Field(default_factory=list)
    outputs: list[PortDecl] = Field(default_factory=list)
    dynamic_inputs: DynamicInputs | None = None
    dynamic_outputs: DynamicOutputs | None = None
    ui: dict[str, FieldUI] = Field(default_factory=dict)


class NodeCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_types: list[NodeTypeInfo]
    prompt_var_pattern: str
    extra_compatible_ports: list[tuple[PortType, PortType]]


NODE_TYPES: list[NodeTypeInfo] = [
    NodeTypeInfo(
        type="start",
        version=1,
        label="Start",
        icon="play",
        category="io",
        description="Flow input; its input_schema properties become output ports.",
        config_schema=StartNodeConfig.model_json_schema(),
        dynamic_outputs="input_schema_properties",
        ui={
            "input_schema": FieldUI(
                widget="schema",
                label="Input Schema",
                help=(
                    "JSON Schema of the flow input. String properties become text "
                    "ports; required for flows published as MCP tools."
                ),
            ),
        },
    ),
    NodeTypeInfo(
        type="end",
        version=1,
        label="End",
        icon="flag",
        category="io",
        description="Flow output; output_from selects the node.port to return.",
        config_schema=EndNodeConfig.model_json_schema(),
        inputs=[PortDecl(name="input", type="text", label="Input")],
        ui={
            "output_from": FieldUI(
                widget="text",
                label="Output From",
                help=(
                    "node_id.port the flow output is read from — set automatically "
                    "when you wire into Input"
                ),
                placeholder="call_1.text",
            ),
        },
    ),
    NodeTypeInfo(
        type="llm_call",
        version=1,
        label="LLM Call",
        icon="sparkles",
        category="llm",
        description="Single completion; {vars} in the prompt become input ports.",
        config_schema=LlmCallNodeConfig.model_json_schema(),
        outputs=[PortDecl(name="text", type="text", label="Text")],
        dynamic_inputs="prompt_vars",
        dynamic_outputs="structured_output_json",
        ui={
            "resource": FieldUI(
                widget="resource",
                label="Model Provider",
                resource_kind="model_provider",
            ),
            "model": FieldUI(widget="text", label="Model", placeholder="provider default"),
            "prompt": FieldUI(widget="prompt", label="Prompt"),
            "system_prompt": FieldUI(
                widget="prompt",
                label="System Prompt",
                help="Same template rules as the prompt — {vars} become input ports.",
            ),
            "structured_output": FieldUI(
                widget="schema",
                label="Output Schema",
                help="JSON Schema; forces JSON mode and adds a json port.",
                toggleable=True,
            ),
            "stream": FieldUI(widget="switch", label="Stream Tokens"),
        },
    ),
    NodeTypeInfo(
        type="mcp_tool",
        version=1,
        label="MCP Tool",
        icon="wrench",
        category="tools",
        description="Call one tool on an MCP server; args map input ports to arguments.",
        config_schema=McpToolNodeConfig.model_json_schema(),
        outputs=[PortDecl(name="result", type="json", label="Result")],
        dynamic_inputs="arg_keys",
        ui={
            "resource": FieldUI(
                widget="resource",
                label="MCP Server",
                resource_kind="mcp_server",
                help="Platform MCP server resource; alternatively set a URL below.",
            ),
            "url": FieldUI(
                widget="text",
                label="Server URL",
                help="Used when no resource is set.",
                advanced=True,
            ),
            "tool": FieldUI(widget="text", label="Tool Name"),
            "args": FieldUI(
                widget="dict",
                label="Arguments",
                help="input port name → tool argument name",
            ),
        },
    ),
    NodeTypeInfo(
        type="retrieval",
        version=1,
        label="Knowledge Base",
        icon="database",
        category="rag",
        description="Similarity search on an existing vector DB (read-only).",
        config_schema=RetrievalNodeConfig.model_json_schema(),
        inputs=[PortDecl(name="query", type="text", label="Query")],
        outputs=[PortDecl(name="documents", type="documents", label="Documents")],
        ui={
            "resource": FieldUI(widget="resource", label="Vector DB", resource_kind="vector_db"),
            "collection": FieldUI(widget="text", label="Collection"),
            "top_k": FieldUI(widget="number", label="Top K"),
            "filter": FieldUI(widget="json", label="Filter", advanced=True),
        },
    ),
]

CATALOG = NodeCatalog(
    node_types=NODE_TYPES,
    prompt_var_pattern=PROMPT_VAR_PATTERN,
    extra_compatible_ports=list(EXTRA_COMPATIBLE_PORTS),
)
