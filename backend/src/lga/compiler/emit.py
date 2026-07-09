"""P5 emit: IR → LangGraph StateGraph (SPEC §5.3-P5)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Hashable
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from lga.compiler.ir import FlowIR, NodeIR
from lga.schema.diagnostics import RuntimeError_, RuntimeErrorCode
from lga.schema.state import FlowState
from lga.sdk.component import BuildContext, NodeFn
from lga.sdk.ports import PortFamily
from lga.sdk.runtime import _stream_write, current_node_id


def is_router_like(node: NodeIR) -> bool:
    return any(o.port.family == PortFamily.ROUTE for o in node.outputs.values())


def _preview(value: Any, limit: int = 200) -> Any:
    try:
        s = repr(value)
    except Exception:  # pragma: no cover - defensive
        return "<unrepresentable>"
    return s if len(s) <= limit else s[: limit - 1] + "…"


def make_node_wrapper(node: NodeIR, fn: NodeFn, ctx: BuildContext) -> NodeFn:
    node_id = node.id
    output_names = set(node.outputs.keys())
    route_labels = {name for name, o in node.outputs.items() if o.port.family == PortFamily.ROUTE}
    router_like = bool(route_labels)

    from langgraph.errors import GraphBubbleUp, GraphInterrupt

    async def wrapped(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        token = current_node_id.set(node_id)
        started = time.perf_counter()
        _stream_write({"event": "node_started", "node_id": node_id, "data": {}})
        try:
            result = await fn(state, config) or {}
        except (GraphInterrupt, GraphBubbleUp):
            raise  # interrupt/control-flow — LangGraph owns these
        except (RuntimeError_, asyncio.CancelledError):
            raise
        except Exception as exc:
            _stream_write(
                {
                    "event": "node_error",
                    "node_id": node_id,
                    "data": {"code": RuntimeErrorCode.RT103.value, "message": str(exc)},
                }
            )
            raise RuntimeError_(
                RuntimeErrorCode.RT103, f"node {node_id!r} failed: {exc}", node_id
            ) from exc
        finally:
            current_node_id.reset(token)

        delta: dict[str, Any] = {}
        ports_delta: dict[str, Any] = {}
        for name in output_names:
            if name in result and name not in route_labels:
                ports_delta[f"{node_id}.{name}"] = result[name]
        if router_like:
            label = result.get("route")
            if label not in route_labels:
                raise RuntimeError_(
                    RuntimeErrorCode.RT102,
                    f"router {node_id!r} emitted invalid label {label!r} "
                    f"(declared: {sorted(route_labels)})",
                    node_id,
                )
            delta["route"] = {node_id: label}
        if "messages" in result:
            delta["messages"] = result["messages"]
        if "data" in result:
            delta["data"] = result["data"]
        if ports_delta:
            delta["ports"] = ports_delta
        _stream_write(
            {
                "event": "node_finished",
                "node_id": node_id,
                "data": {
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "outputs_preview": {k: _preview(v) for k, v in ports_delta.items()},
                    **({"route": delta["route"][node_id]} if "route" in delta else {}),
                },
            }
        )
        return delta

    return wrapped


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


def wrap_component(component_cls: Any, ctx: BuildContext) -> NodeFn:
    """Public wrapper builder — used by exported standalone flow.py files."""
    from types import SimpleNamespace

    outputs = {o.name: o for o in component_cls.outputs_for_config(ctx.config)}
    shim = SimpleNamespace(id=ctx.node_id, outputs=outputs)
    fn = component_cls().build(ctx)
    return make_node_wrapper(shim, fn, ctx)  # type: ignore[arg-type]


def emit(ir: FlowIR, contexts: dict[str, BuildContext]) -> StateGraph[FlowState]:
    graph: StateGraph[FlowState] = StateGraph(FlowState)
    providers = pure_tool_providers(ir)

    for node in ir.nodes.values():
        if node.id in providers:
            continue
        instance = node.component()
        fn = instance.build(contexts[node.id])
        graph.add_node(node.id, make_node_wrapper(node, fn, contexts[node.id]))

    if "start" in ir.nodes:
        graph.add_edge(START, "start")

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
        graph.add_edge(pair[0], pair[1])

    for node_id, table in routers.items():

        def make_reader(nid: str) -> Callable[[dict[str, Any]], str]:
            def route_reader(state: dict[str, Any]) -> str:
                return cast(str, state.get("route", {}).get(nid, ""))

            return route_reader

        graph.add_conditional_edges(
            node_id, make_reader(node_id), cast("dict[Hashable, str]", dict(table))
        )

    # terminal nodes and dead-end branches finish the graph
    for node in ir.nodes.values():
        if node.id in providers:
            continue
        has_control_out = any(e.kind in ("data", "router") for e in ir.out_edges(node.id))
        if not has_control_out:
            graph.add_edge(node.id, END)

    return graph
