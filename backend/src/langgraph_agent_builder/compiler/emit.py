"""P5 emit: IR → LangGraph StateGraph (SPEC §5.3-P5).

Interprets the shared graph plan (``langgraph_agent_builder.compiler.plan``); component ``build()``
failures become E015 diagnostics instead of escaping the pipeline (§5.4).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Callable, Hashable
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from langgraph_agent_builder.compiler import plan as plan_pass
from langgraph_agent_builder.compiler.ir import FlowIR

# re-exported for backwards compatibility (they lived here before plan.py)
from langgraph_agent_builder.compiler.plan import is_router_like, pure_tool_providers
from langgraph_agent_builder.schema.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    RuntimeError_,
    RuntimeErrorCode,
)
from langgraph_agent_builder.schema.state import FlowState
from langgraph_agent_builder.sdk.component import BuildContext, Component, NodeFn
from langgraph_agent_builder.sdk.outputs import Output
from langgraph_agent_builder.sdk.ports import PortFamily
from langgraph_agent_builder.sdk.runtime import current_node_id, get_run_context, stream_write

__all__ = [
    "emit",
    "is_router_like",
    "make_node_wrapper",
    "pure_tool_providers",
    "wrap_component",
]


def _preview(value: Any, limit: int = 200) -> Any:
    try:
        s = repr(value)
    except Exception:  # pragma: no cover - defensive
        return "<unrepresentable>"
    return s if len(s) <= limit else s[: limit - 1] + "…"


# Node-run timeline snapshots (REFACTOR.md §7): the wrapper holds the FULL input
# state and output delta, so we record a JSON-safe, size-capped projection of
# each. Messages / pydantic models are coerced; oversized blobs are truncated.
_SNAPSHOT_MAX_CHARS = 8000
_SNAPSHOT_STR_CAP = 2000


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= _SNAPSHOT_STR_CAP else value[: _SNAPSHOT_STR_CAP - 1] + "…"
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return _json_safe(dump(mode="json"))
        except Exception:  # pragma: no cover - defensive
            pass
    if hasattr(value, "content"):  # LangChain message-like
        return {
            "type": getattr(value, "type", type(value).__name__),
            "content": _json_safe(value.content),
        }
    return _preview(value, _SNAPSHOT_STR_CAP)


def _snapshot(value: Any) -> dict[str, Any]:
    """JSON-safe, size-capped snapshot of a node's input state / output delta."""
    safe = _json_safe(value)
    if not isinstance(safe, dict):
        safe = {"value": safe}
    try:
        blob = json.dumps(safe)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return {"__unserializable__": _preview(value, _SNAPSHOT_MAX_CHARS)}
    if len(blob) > _SNAPSHOT_MAX_CHARS:
        return {"__truncated__": True, "preview": blob[:_SNAPSHOT_MAX_CHARS]}
    return safe


def make_node_wrapper(
    node_id: str,
    outputs: dict[str, Output],
    fn: NodeFn,
    ctx: BuildContext,
    instance: Component | None = None,
) -> NodeFn:
    output_names = set(outputs.keys())
    route_labels = {name for name, o in outputs.items() if o.port.family == PortFamily.ROUTE}
    router_like = bool(route_labels)
    # Output.method dispatch (SPEC §4.5): outputs naming a method are computed
    # by that bound method (multi-output components, Langflow parity). Bound
    # eagerly so a missing method fails at compile (E015), not mid-run.
    method_fns: dict[str, Callable[..., Any]] = {}
    if instance is not None:
        for name, out in outputs.items():
            if out.method:
                method_fns[name] = getattr(instance, out.method)

    from langgraph.errors import GraphBubbleUp, GraphInterrupt

    async def wrapped(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        token = current_node_id.set(node_id)
        started = time.perf_counter()
        # Per-node run timeline (REFACTOR.md §7): record from the wrapper, which
        # sees the FULL input state / output delta. ``record_node_run`` is None
        # under vanilla LangGraph / the test harness ⇒ recording is a no-op and
        # the iteration counter is never touched.
        run_ctx = get_run_context(config)
        recorder = run_ctx.record_node_run
        iteration = run_ctx.next_iteration(node_id) if recorder is not None else 0
        if recorder is not None:
            recorder(
                {
                    "event": "started",
                    "node_id": node_id,
                    "iteration": iteration,
                    "input_snapshot": _snapshot(state),
                }
            )
        stream_write({"event": "node_started", "node_id": node_id, "data": {}})
        try:
            result = await fn(state, config) or {}
            for name, method_fn in method_fns.items():
                if name in result:
                    continue  # the NodeFn already produced this channel
                value = method_fn(state, config)
                if inspect.isawaitable(value):
                    value = await value
                result[name] = value
        except (GraphInterrupt, GraphBubbleUp):
            if recorder is not None:
                recorder({"event": "interrupted", "node_id": node_id, "iteration": iteration})
            raise  # interrupt/control-flow — LangGraph owns these
        except asyncio.CancelledError:
            raise
        except RuntimeError_ as exc:
            if recorder is not None:
                recorder(
                    {
                        "event": "error",
                        "node_id": node_id,
                        "iteration": iteration,
                        "error_code": exc.code.value,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                )
            raise
        except Exception as exc:
            stream_write(
                {
                    "event": "node_error",
                    "node_id": node_id,
                    "data": {"code": RuntimeErrorCode.RT103.value, "message": str(exc)},
                }
            )
            if recorder is not None:
                recorder(
                    {
                        "event": "error",
                        "node_id": node_id,
                        "iteration": iteration,
                        "error_code": RuntimeErrorCode.RT103.value,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
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
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        route_label = delta["route"][node_id] if "route" in delta else None
        stream_write(
            {
                "event": "node_finished",
                "node_id": node_id,
                "data": {
                    "duration_ms": duration_ms,
                    "outputs_preview": {k: _preview(v) for k, v in ports_delta.items()},
                    **({"route": route_label} if route_label is not None else {}),
                },
            }
        )
        if recorder is not None:
            recorder(
                {
                    "event": "finished",
                    "node_id": node_id,
                    "iteration": iteration,
                    "output_snapshot": _snapshot(delta),
                    "duration_ms": duration_ms,
                    **({"route": route_label} if route_label is not None else {}),
                }
            )
        return delta

    return wrapped


def wrap_component(component_cls: type[Component], ctx: BuildContext) -> NodeFn:
    """Public wrapper builder — used by exported standalone flow.py files."""
    instance = component_cls()
    outputs = {o.name: o for o in component_cls.outputs_for_config(ctx.config)}
    fn = instance.build(ctx)
    return make_node_wrapper(ctx.node_id, outputs, fn, ctx, instance=instance)


def emit(
    ir: FlowIR, contexts: dict[str, BuildContext]
) -> tuple[StateGraph[FlowState] | None, list[Diagnostic]]:
    """Interpret the graph plan against a StateGraph.

    ``build()`` may raise (third-party components validating config combos) —
    each failure becomes an E015 ERROR diagnostic ('all diagnostics, no
    exceptions', §5.3/§5.4) and no builder is returned.
    """
    graph: StateGraph[FlowState] = StateGraph(FlowState)
    diagnostics: list[Diagnostic] = []
    ops = plan_pass.graph_plan(ir)

    for op in ops:
        if not isinstance(op, plan_pass.AddNode):
            continue
        node = ir.nodes[op.node_id]
        try:
            instance = node.component()
            fn = instance.build(contexts[node.id])
            wrapper = make_node_wrapper(node.id, node.outputs, fn, contexts[node.id], instance)
        except Exception as exc:
            diagnostics.append(
                Diagnostic.make(
                    DiagnosticCode.E015,
                    f"component {node.component.component_id} build() failed: {exc}",
                    node_id=node.id,
                    fix_hint="Fix the node's configuration or the component's build().",
                )
            )
            continue
        graph.add_node(node.id, wrapper)
    if diagnostics:
        return None, diagnostics

    for op in ops:
        match op:
            case plan_pass.AddStartEdge(target=target):
                graph.add_edge(START, target)
            case plan_pass.AddEdge(source=source, target=target):
                graph.add_edge(source, target)
            case plan_pass.AddConditionalEdges(node_id=node_id, table=table):

                def make_reader(nid: str) -> Callable[[dict[str, Any]], str]:
                    def route_reader(state: dict[str, Any]) -> str:
                        return cast(str, state.get("route", {}).get(nid, ""))

                    return route_reader

                graph.add_conditional_edges(
                    node_id, make_reader(node_id), cast("dict[Hashable, str]", dict(table))
                )
            case plan_pass.Finish(node_id=node_id):
                graph.add_edge(node_id, END)
            case _:
                pass

    return graph, diagnostics
