"""Unit tests for compiler.ir (FlowIR edge filters + NodeIR/EdgeIR props)."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.compiler.ir import EdgeIR, FlowIR, NodeIR
from langgraph_agent_builder.schema.flowspec import (
    EdgeEndpointSource,
    EdgeEndpointTarget,
    EdgeSpec,
    FlowMeta,
    FlowSpec,
    NodeSpec,
)
from langgraph_agent_builder.sdk.component import BuildContext, Component, NodeKind
from langgraph_agent_builder.sdk.outputs import Output
from langgraph_agent_builder.sdk.ports import ROUTE


class _Task(Component):
    component_id = "test.task"

    def build(self, ctx: BuildContext) -> Any:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node


class _Router(Component):
    component_id = "test.router"
    node_kind = NodeKind.ROUTER
    outputs = [Output(name="yes", port=ROUTE), Output(name="no", port=ROUTE)]

    def build(self, ctx: BuildContext) -> Any:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node


def _edge(edge_id: str, kind: str, src: str, dst: str) -> EdgeIR:
    return EdgeIR(
        spec=EdgeSpec(
            id=edge_id,
            kind=kind,  # type: ignore[arg-type]
            source=EdgeEndpointSource(node=src, output="o"),
            target=EdgeEndpointTarget(node=dst, input="i"),
        )
    )


def _build_ir() -> FlowIR:
    spec = FlowSpec(flow=FlowMeta(name="ir", slug="ir"))
    ir = FlowIR(spec=spec)
    ir.nodes = {
        "a": NodeIR(spec=NodeSpec(id="a", component_id="test.task"), component=_Task),
        "r": NodeIR(spec=NodeSpec(id="r", component_id="test.router"), component=_Router),
        "b": NodeIR(spec=NodeSpec(id="b", component_id="test.task"), component=_Task),
    }
    ir.edges = [
        _edge("d1", "data", "a", "r"),
        _edge("t1", "tool", "a", "b"),
        _edge("rt1", "router", "r", "b"),
    ]
    return ir


def test_edge_kind_filters_partition_edges() -> None:
    ir = _build_ir()
    assert [e.id for e in ir.data_edges()] == ["d1"]
    assert [e.id for e in ir.tool_edges()] == ["t1"]
    assert [e.id for e in ir.router_edges()] == ["rt1"]


def test_out_and_in_edges() -> None:
    ir = _build_ir()
    assert {e.id for e in ir.out_edges("a")} == {"d1", "t1"}
    assert {e.id for e in ir.in_edges("b")} == {"t1", "rt1"}
    assert ir.out_edges("b") == []


def test_node_ir_id_and_kind_properties() -> None:
    ir = _build_ir()
    assert ir.nodes["a"].id == "a"
    assert ir.nodes["a"].kind == NodeKind.TASK
    assert ir.nodes["r"].kind == NodeKind.ROUTER


def test_edge_ir_id_and_kind_properties() -> None:
    ir = _build_ir()
    tool_edge = ir.tool_edges()[0]
    assert tool_edge.id == "t1"
    assert tool_edge.kind == "tool"
