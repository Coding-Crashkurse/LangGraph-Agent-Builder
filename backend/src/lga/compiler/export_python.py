"""Export-to-Python (SPEC §5.7): FlowSpec → standalone flow.py.

The exported file renders the same graph plan the compiler emits
(``lga.compiler.plan``; golden-tested in tests/test_export_python.py) and runs
under vanilla LangGraph — only lga component classes are imported, not the
server.
"""

from __future__ import annotations

import json
from typing import Any

from lga.compiler import compile_flow
from lga.compiler import plan as plan_pass
from lga.schema.flowspec import FlowSpec
from lga.sdk.registry import ComponentRegistry


def _render_config(config: dict[str, Any]) -> str:
    """Config literal. $secret/$var refs become the LGA_CRED_/LGA_VAR_ env
    lookups ``EnvVariablesProvider`` reads (headless convention, resolve.py);
    $vectorstore refs become the VectorStoreHandle P2 would produce."""

    def render(value: Any) -> str:
        if isinstance(value, dict):
            if "$vectorstore" in value:
                name = str(value["$vectorstore"])
                return (
                    f"VectorStoreHandle(connection={name!r}, "
                    f"collection={value.get('collection')!r})"
                )
            if set(value.keys()) == {"$secret"}:
                return f'os.environ["LGA_CRED_{str(value["$secret"]).upper()}"]'
            if set(value.keys()) == {"$var"}:
                return f'os.environ["LGA_VAR_{str(value["$var"]).upper()}"]'
            inner = ", ".join(f"{k!r}: {render(v)}" for k, v in value.items())
            return "{" + inner + "}"
        if isinstance(value, list):
            return "[" + ", ".join(render(v) for v in value) + "]"
        return repr(value)

    return render(config)


def _has_vectorstore_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return "$vectorstore" in value or any(_has_vectorstore_ref(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_vectorstore_ref(v) for v in value)
    return False


def export_python(spec: FlowSpec, registry: ComponentRegistry) -> str:
    compiled = compile_flow(spec, registry=registry, use_cache=False)
    if compiled.ir is None or not compiled.ok:
        errors = "; ".join(
            f"{d.code.value}: {d.message}" for d in compiled.diagnostics if d.severity == "error"
        )
        raise ValueError(f"cannot export a flow with compile errors: {errors}")
    ir = compiled.ir

    imports: dict[str, set[str]] = {}
    for node in ir.nodes.values():
        imports.setdefault(node.component.__module__, set()).add(node.component.__name__)

    lines: list[str] = [
        '"""Exported by lga — runs under vanilla LangGraph (SPEC §5.7)."""',
        "",
        "import os",
        "",
        "from langgraph.graph import END, START, StateGraph",
        "",
        "from lga.compiler.emit import wrap_component",
        "from lga.schema.state import FlowState",
        "from lga.sdk.component import BuildContext, InputBinding",
    ]
    if any(_has_vectorstore_ref(n.config) for n in ir.spec.nodes):
        lines.append("from lga.sdk.ports import VectorStoreHandle")
    lines.append("")
    for module, names in sorted(imports.items()):
        lines.append(f"from {module} import {', '.join(sorted(names))}")
    lines += ["", "builder = StateGraph(FlowState)", ""]

    for op in plan_pass.graph_plan(ir):
        match op:
            case plan_pass.AddNode(node_id=node_id):
                node = ir.nodes[node_id]
                raw_config = next(n.config for n in ir.spec.nodes if n.id == node_id)
                bindings: list[str] = []
                for e in ir.in_edges(node_id):
                    if e.kind != "data":
                        continue
                    channel = f"{e.spec.source.node}.{e.spec.source.output}"
                    coercion = f", coercion={e.coercion!r}" if e.coercion else ""
                    bindings.append(
                        f'"{e.spec.target.input}": InputBinding(input_name='
                        f'"{e.spec.target.input}", channel="{channel}"{coercion})'
                    )
                lines += [
                    f"# ---- node: {node_id} ({node.component.component_id})",
                    f'_{node_id}_ctx = BuildContext(node_id="{node_id}", '
                    f"config={_render_config(raw_config)}, "
                    f"input_bindings={{{', '.join(bindings)}}})",
                    f'builder.add_node("{node_id}", '
                    f"wrap_component({node.component.__name__}, _{node_id}_ctx))",
                    "",
                ]
            case plan_pass.AddStartEdge(target=target):
                lines.append(f'builder.add_edge(START, "{target}")')
            case plan_pass.AddEdge(source=source, target=target):
                lines.append(f'builder.add_edge("{source}", "{target}")')
            case plan_pass.AddConditionalEdges(node_id=node_id, table=table):
                lines += [
                    "",
                    f'builder.add_conditional_edges("{node_id}", '
                    f'lambda state, _nid="{node_id}": state.get("route", {{}}).get(_nid, ""), '
                    f"{json.dumps(table)})",
                ]
            case plan_pass.Finish(node_id=node_id):
                lines.append(f'builder.add_edge("{node_id}", END)')

    lines += [
        "",
        "graph = builder.compile()",
        "",
        'if __name__ == "__main__":',
        "    import asyncio",
        "",
        "    from langchain_core.messages import HumanMessage",
        "",
        "    state = {",
        '        "messages": [HumanMessage("hello")], "ports": {}, "route": {},',
        '        "run_meta": {"input_text": "hello", "run_id": "export", "thread_id": "export"},',
        "    }",
        "    result = asyncio.run(graph.ainvoke(state))",
        '    print(result.get("ports", {}))',
        "",
    ]
    return "\n".join(lines)
