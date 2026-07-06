"""Export-to-Python (SPEC §5.7): FlowSpec → standalone flow.py.

The exported file constructs the same StateGraph topology the compiler emits
(golden-tested in tests/test_export_python.py) and runs under vanilla
LangGraph — only lga component classes are imported, not the server.
"""

from __future__ import annotations

import json
from typing import Any

from lga.compiler import compile_flow
from lga.schema.flowspec import FlowSpec
from lga.sdk.registry import ComponentRegistry


def _render_config(config: dict[str, Any]) -> str:
    """Config literal; $secret/$var refs become os.environ lookups."""

    def render(value: Any) -> str:
        if isinstance(value, dict):
            if set(value.keys()) == {"$secret"} or set(value.keys()) == {"$var"}:
                name = str(next(iter(value.values())))
                return f'os.environ["{name.upper()}"]'
            inner = ", ".join(f"{k!r}: {render(v)}" for k, v in value.items())
            return "{" + inner + "}"
        if isinstance(value, list):
            return "[" + ", ".join(render(v) for v in value) + "]"
        return repr(value)

    return render(config)


def export_python(spec: FlowSpec, registry: ComponentRegistry) -> str:
    compiled = compile_flow(spec, registry=registry, use_cache=False)
    if compiled.ir is None or not compiled.ok:
        errors = "; ".join(
            f"{d.code.value}: {d.message}" for d in compiled.diagnostics if d.severity == "error"
        )
        raise ValueError(f"cannot export a flow with compile errors: {errors}")
    ir = compiled.ir

    from lga.compiler.emit import pure_tool_providers

    providers = pure_tool_providers(ir)
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
        "",
    ]
    for module, names in sorted(imports.items()):
        lines.append(f"from {module} import {', '.join(sorted(names))}")
    lines += ["", "builder = StateGraph(FlowState)", ""]

    for node in ir.nodes.values():
        if node.id in providers:
            continue  # tool providers contribute tools, not graph nodes
        raw_config = next(n.config for n in ir.spec.nodes if n.id == node.id)
        bindings: list[str] = []
        for e in ir.in_edges(node.id):
            if e.kind != "data":
                continue
            channel = f"{e.spec.source.node}.{e.spec.source.output}"
            coercion = f", coercion={e.coercion!r}" if e.coercion else ""
            bindings.append(
                f'"{e.spec.target.input}": InputBinding(input_name='
                f'"{e.spec.target.input}", channel="{channel}"{coercion})'
            )
        lines += [
            f"# ---- node: {node.id} ({node.component.component_id})",
            f'_{node.id}_ctx = BuildContext(node_id="{node.id}", '
            f"config={_render_config(raw_config)}, "
            f"input_bindings={{{', '.join(bindings)}}})",
            f'builder.add_node("{node.id}", '
            f"wrap_component({node.component.__name__}, _{node.id}_ctx))",
            "",
        ]

    lines.append('builder.add_edge(START, "start")')
    seen_pairs: set[tuple[str, str]] = set()
    routers: dict[str, dict[str, str]] = {}
    for e in ir.edges:
        if e.kind == "router":
            routers.setdefault(e.spec.source.node, {})[e.spec.source.output] = e.spec.target.node
        elif e.kind == "data":
            pair = (e.spec.source.node, e.spec.target.node)
            src = ir.nodes.get(pair[0])
            from lga.compiler.emit import is_router_like

            if pair in seen_pairs or (src and is_router_like(src)):
                continue
            seen_pairs.add(pair)
            lines.append(f'builder.add_edge("{pair[0]}", "{pair[1]}")')
    for node_id, table in sorted(routers.items()):
        lines += [
            "",
            f'builder.add_conditional_edges("{node_id}", '
            f'lambda state, _nid="{node_id}": state.get("route", {{}}).get(_nid, ""), '
            f"{json.dumps(table)})",
        ]
    for node in ir.nodes.values():
        if node.id in providers:
            continue
        if not any(e.kind in ("data", "router") for e in ir.out_edges(node.id)):
            lines.append(f'builder.add_edge("{node.id}", END)')

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
