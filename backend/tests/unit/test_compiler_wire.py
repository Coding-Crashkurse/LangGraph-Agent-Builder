"""Unit tests for lga.compiler.wire (P4: ports→channels, constants, tool binding)."""

from __future__ import annotations

from typing import Any

from lga.compiler.ir import EdgeIR, FlowIR, NodeIR
from lga.compiler.wire import channel_for, wire
from lga.schema.flowspec import (
    EdgeEndpointSource,
    EdgeEndpointTarget,
    EdgeSpec,
    FlowMeta,
    FlowSpec,
    NodeSpec,
)
from lga.sdk.component import BuildContext, Component
from lga.sdk.ports import ToolDef

# --------------------------------------------------------------------------- test components


class _Plain(Component):
    """A non-tool source/consumer node."""

    component_id = "test.plain"

    def build(self, ctx: BuildContext) -> Any:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node


class _ProvidesList(Component):
    component_id = "test.provideslist"

    def build(self, ctx: BuildContext) -> Any:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node

    def provide_tools(self, ctx: BuildContext) -> list[ToolDef]:
        return [ToolDef(name="alpha"), ToolDef(name="beta")]


class _ProvidesSingle(Component):
    component_id = "test.providessingle"

    def build(self, ctx: BuildContext) -> Any:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node

    def provide_tools(self, ctx: BuildContext) -> ToolDef:
        return ToolDef(name="solo")


# --------------------------------------------------------------------------- helpers


def _ir(nodes: dict[str, type[Component]], edges: list[EdgeIR]) -> FlowIR:
    spec = FlowSpec(flow=FlowMeta(name="w", slug="w"))
    ir = FlowIR(spec=spec)
    ir.nodes = {
        nid: NodeIR(spec=NodeSpec(id=nid, component_id=comp.component_id), component=comp)
        for nid, comp in nodes.items()
    }
    ir.edges = edges
    return ir


def _tool_edge(src: str, dst: str) -> EdgeIR:
    return EdgeIR(
        spec=EdgeSpec(
            id=f"t_{src}_{dst}",
            kind="tool",
            source=EdgeEndpointSource(node=src, output="toolset"),
            target=EdgeEndpointTarget(node=dst, input="tools"),
        )
    )


# --------------------------------------------------------------------------- channel_for


def test_channel_for_joins_node_and_output() -> None:
    assert channel_for("nodeA", "message") == "nodeA.message"


# --------------------------------------------------------------------------- data bindings


def test_data_edge_binding_carries_channel_and_coercion() -> None:
    ir = _ir(
        {"a": _Plain, "b": _Plain},
        [
            EdgeIR(
                spec=EdgeSpec(
                    id="d1",
                    kind="data",
                    source=EdgeEndpointSource(node="a", output="message"),
                    target=EdgeEndpointTarget(node="b", input="input"),
                ),
                coercion="message_to_text",
            )
        ],
    )
    contexts = wire(ir)
    binding = contexts["b"].input_bindings["input"]
    assert binding.channel == "a.message"
    assert binding.coercion == "message_to_text"
    # node.build_ctx is stashed back onto the IR node
    assert ir.nodes["b"].build_ctx is contexts["b"]


def test_router_edge_does_not_create_data_binding() -> None:
    ir = _ir(
        {"a": _Plain, "b": _Plain},
        [
            EdgeIR(
                spec=EdgeSpec(
                    id="r1",
                    kind="router",
                    source=EdgeEndpointSource(node="a", output="approve"),
                    target=EdgeEndpointTarget(node="b", input="input"),
                )
            )
        ],
    )
    contexts = wire(ir)
    assert contexts["b"].input_bindings == {}


def test_constants_become_constant_bindings() -> None:
    ir = _ir({"a": _Plain, "b": _Plain}, [])
    contexts = wire(ir, constants={"b": {"foo": "bar"}})
    binding = contexts["b"].input_bindings["foo"]
    assert binding.channel is None
    assert binding.constant == "bar"


def test_flow_id_defaults_to_slug() -> None:
    ir = _ir({"a": _Plain}, [])
    contexts = wire(ir)
    assert contexts["a"].flow_id == "w"  # FlowMeta.slug
    contexts2 = wire(ir, flow_id="explicit")
    assert contexts2["a"].flow_id == "explicit"


# --------------------------------------------------------------------------- tool bindings


def test_tool_edge_from_list_provider() -> None:
    ir = _ir({"prov": _ProvidesList, "agent": _Plain}, [_tool_edge("prov", "agent")])
    contexts = wire(ir)
    names = [t.name for t in contexts["agent"].tools]
    assert names == ["alpha", "beta"]


def test_tool_edge_from_single_provider_is_wrapped_in_list() -> None:
    ir = _ir({"prov": _ProvidesSingle, "agent": _Plain}, [_tool_edge("prov", "agent")])
    contexts = wire(ir)
    tools = contexts["agent"].tools
    assert len(tools) == 1
    assert tools[0].name == "solo"


def test_tool_edge_from_non_provider_yields_no_tools() -> None:
    ir = _ir({"prov": _Plain, "agent": _Plain}, [_tool_edge("prov", "agent")])
    contexts = wire(ir)
    assert contexts["agent"].tools == []


def test_tool_edge_from_tool_mode_node_uses_node_as_tool() -> None:
    """A calculator (tool_mode) wired via a tool edge becomes a callable ToolDef."""
    from lga.components.tools.basic_tools import Calculator

    ir = _ir({"calc": Calculator, "agent": _Plain}, [_tool_edge("calc", "agent")])
    contexts = wire(ir)
    tools = contexts["agent"].tools
    assert len(tools) == 1
    assert tools[0].name  # slugified calculator label / tool name
