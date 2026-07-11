"""P4 wire: ports→state channels, coercions, tool binding (SPEC §5.3-P4)."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.compiler.ir import FlowIR
from langgraph_agent_builder.sdk.component import BuildContext, InputBinding, SecretsResolver
from langgraph_agent_builder.sdk.ports import ToolDef


def channel_for(edge_source_node: str, edge_source_output: str) -> str:
    return f"{edge_source_node}.{edge_source_output}"


def _tool_defs_for_provider(ir: FlowIR, provider_id: str, ctx: BuildContext) -> list[Any]:
    """ToolDefs (or a LazyToolset) contributed by a tool-edge source node."""
    node = ir.nodes[provider_id]
    instance = node.component()
    provide = getattr(instance, "provide_tools", None)
    if callable(provide):
        provided = provide(ctx)
        return provided if isinstance(provided, list) else [provided]
    if node.component.tool_mode_supported and node.component.tool_mode_enabled(node.config):
        from langgraph_agent_builder.runtime.tools import node_as_tool

        return [node_as_tool(node, ctx)]
    return []


def wire(
    ir: FlowIR,
    *,
    flow_id: str = "",
    secrets: SecretsResolver | None = None,
    constants: dict[str, dict[str, Any]] | None = None,
    registry: Any = None,
    settings: Any = None,
) -> dict[str, BuildContext]:
    """Build a BuildContext per node: input bindings, coercions, tools."""
    constants = constants or {}
    contexts: dict[str, BuildContext] = {}

    for node in ir.nodes.values():
        bindings: dict[str, InputBinding] = {}
        for e in ir.in_edges(node.id):
            if e.kind != "data":
                continue
            bindings[e.spec.target.input] = InputBinding(
                input_name=e.spec.target.input,
                channel=channel_for(e.spec.source.node, e.spec.source.output),
                coercion=e.coercion,
            )
        for name, value in (constants.get(node.id) or {}).items():
            bindings[name] = InputBinding(input_name=name, channel=None, constant=value)

        contexts[node.id] = BuildContext(
            node_id=node.id,
            flow_id=flow_id or ir.spec.flow.slug,
            label=node.spec.label or node.component.display_name,
            config=node.config,
            fields=node.component.field_map(),
            secrets=secrets or SecretsResolver(),
            registry=registry,
            input_bindings=bindings,
            settings=settings,
        )
        node.build_ctx = contexts[node.id]

    # tools after all contexts exist (provider ctx must be available)
    for node in ir.nodes.values():
        tool_sources = [e.spec.source.node for e in ir.in_edges(node.id) if e.kind == "tool"]
        tools: list[ToolDef | Any] = []
        for src_id in tool_sources:
            tools.extend(_tool_defs_for_provider(ir, src_id, contexts[src_id]))
        contexts[node.id].tools = tools

    return contexts
