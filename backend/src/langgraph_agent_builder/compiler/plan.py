"""Shared graph-construction plan (SPEC §5.3-P5, §5.7).

``graph_plan`` turns a resolved FlowIR into an ordered list of primitive graph
operations — skip pure tool providers, dedup data edges per node pair, suppress
direct edges out of router-like nodes, route tables, terminals → END. ``emit``
interprets the ops against a LangGraph ``StateGraph``; ``export_python`` renders
each op as a source line. One algorithm, two renderers — emission semantics can
never drift between the runtime graph and exported flow.py files.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph_agent_builder.compiler.ir import FlowIR, NodeIR
from langgraph_agent_builder.sdk.ports import PortFamily


def is_router_like(node: NodeIR) -> bool:
    return any(o.port.family == PortFamily.ROUTE for o in node.outputs.values())


def pure_tool_providers(ir: FlowIR) -> set[str]:
    """Nodes whose only role is contributing tools — never graph nodes."""
    out: set[str] = set()
    for node in ir.nodes.values():
        edges_out = ir.out_edges(node.id)
        edges_in = ir.in_edges(node.id)
        if (
            edges_out
            and all(e.kind == "tool" for e in edges_out)
            and all(e.kind == "tool" for e in edges_in)
        ):
            out.add(node.id)
    return out


@dataclass(frozen=True)
class AddNode:
    node_id: str


@dataclass(frozen=True)
class AddStartEdge:
    target: str  # START → target


@dataclass(frozen=True)
class AddEdge:
    source: str
    target: str


@dataclass(frozen=True)
class AddConditionalEdges:
    node_id: str
    table: dict[str, str]  # branch label → target node


@dataclass(frozen=True)
class Finish:
    node_id: str  # node → END


GraphOp = AddNode | AddStartEdge | AddEdge | AddConditionalEdges | Finish


def graph_plan(ir: FlowIR) -> list[GraphOp]:
    """Ordered operations building the LangGraph topology from the IR."""
    providers = pure_tool_providers(ir)
    ops: list[GraphOp] = [AddNode(n.id) for n in ir.nodes.values() if n.id not in providers]

    if "start" in ir.nodes:
        ops.append(AddStartEdge("start"))

    # plain control edges from data edges, dedup per node pair
    seen_pairs: set[tuple[str, str]] = set()
    routers: dict[str, dict[str, str]] = {}
    for e in ir.edges:
        if e.kind == "router":
            routers.setdefault(e.spec.source.node, {})[e.spec.source.output] = e.spec.target.node
            continue
        if e.kind != "data":
            continue
        pair = (e.spec.source.node, e.spec.target.node)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        src = ir.nodes.get(pair[0])
        if src is not None and is_router_like(src):
            continue  # router-like nodes leave only via conditional edges
        ops.append(AddEdge(*pair))

    for node_id in sorted(routers):
        ops.append(AddConditionalEdges(node_id, dict(routers[node_id])))

    # terminal nodes and dead-end branches finish the graph
    for node in ir.nodes.values():
        if node.id in providers:
            continue
        if not any(e.kind in ("data", "router") for e in ir.out_edges(node.id)):
            ops.append(Finish(node.id))
    return ops
