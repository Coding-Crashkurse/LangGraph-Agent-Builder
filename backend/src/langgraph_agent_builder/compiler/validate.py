"""P3 validate: the rule table (SPEC §5.4). All diagnostics, no exceptions."""

from __future__ import annotations

from collections import defaultdict

from langgraph_agent_builder.compiler.ir import FlowIR, NodeIR
from langgraph_agent_builder.schema.diagnostics import Diagnostic, DiagnosticCode
from langgraph_agent_builder.sdk.component import NodeKind
from langgraph_agent_builder.sdk.ports import PortFamily, check_compatibility


def router_like(node: NodeIR) -> bool:
    """Routers AND interrupt nodes with ROUTE branches (e.g. Human Approval)."""
    return any(o.port.family == PortFamily.ROUTE for o in node.outputs.values())


WARNING_BY_CODE = {
    "W201": "untyped (ANY) edge — no structural guarantees",
    "W202": "auto list-wrap coercion inserted",
}


def _control_successors(ir: FlowIR) -> dict[str, set[str]]:
    succ: dict[str, set[str]] = defaultdict(set)
    for e in ir.edges:
        if e.kind in ("data", "router"):
            succ[e.spec.source.node].add(e.spec.target.node)
    return succ


def _reachable(succ: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(succ.get(cur, ()))
    return seen


def _sccs(nodes: list[str], succ: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan strongly-connected components."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    def strongconnect(v: str) -> None:
        nonlocal counter
        work = [(v, iter(sorted(succ.get(v, ()))))]
        index[v] = low[v] = counter
        counter += 1
        stack.append(v)
        on_stack.add(v)
        while work:
            node, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(succ.get(w, ())))))
                    advanced = True
                    break
                elif w in on_stack:
                    low[node] = min(low[node], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                result.append(comp)

    for v in nodes:
        if v not in index:
            strongconnect(v)
    return result


def validate(ir: FlowIR) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    D = Diagnostic.make

    # ---------------------------------------------------------------- edges
    for e in ir.edges:
        src = ir.nodes.get(e.spec.source.node)
        tgt = ir.nodes.get(e.spec.target.node)
        if src is None or tgt is None:
            continue  # unknown component already reported (E002) or parse error

        if e.spec.target.node == "start":
            diags.append(D(DiagnosticCode.E024, "edge into `start`", edge_id=e.id))
        if src.kind == NodeKind.TERMINAL:
            diags.append(
                D(DiagnosticCode.E024, f"edge out of terminal node {src.id!r}", edge_id=e.id)
            )

        if e.kind == "tool":
            if e.source_port is None or e.source_port.family != PortFamily.TOOLSET:
                diags.append(
                    D(
                        DiagnosticCode.E021,
                        f"tool edge from non-Toolset output "
                        f"{e.spec.source.node}.{e.spec.source.output}",
                        edge_id=e.id,
                    )
                )
            if e.target_port is None or e.target_port.family != PortFamily.TOOLSET:
                diags.append(
                    D(
                        DiagnosticCode.E021,
                        f"tool edge into non-Tools port {e.spec.target.node}.{e.spec.target.input}",
                        edge_id=e.id,
                    )
                )
            continue

        if e.kind == "router":
            if not router_like(src):
                diags.append(
                    D(
                        DiagnosticCode.E023,
                        f"router edge from non-router node {src.id!r}",
                        edge_id=e.id,
                    )
                )
            elif e.spec.source.output not in src.outputs:
                diags.append(
                    D(
                        DiagnosticCode.E022,
                        f"router {src.id!r} has no branch {e.spec.source.output!r}",
                        edge_id=e.id,
                        node_id=src.id,
                    )
                )
            continue

        # ---- data edge
        if e.source_port is not None and e.source_port.family == PortFamily.ROUTE:
            diags.append(
                D(
                    DiagnosticCode.E023,
                    "ROUTE ports carry control only — use a router edge",
                    edge_id=e.id,
                )
            )
            continue
        if e.source_port is None:
            diags.append(
                D(
                    DiagnosticCode.E020,
                    f"unknown output {e.spec.source.output!r} on node {src.id!r}",
                    edge_id=e.id,
                    node_id=src.id,
                )
            )
            continue
        if e.target_port is None:
            diags.append(
                D(
                    DiagnosticCode.E020,
                    f"unknown input {e.spec.target.input!r} on node {tgt.id!r}",
                    edge_id=e.id,
                    node_id=tgt.id,
                )
            )
            continue
        compat = check_compatibility(e.source_port, e.target_port)
        if not compat.compatible:
            diags.append(
                D(
                    DiagnosticCode.E020,
                    f"edge type-incompatible: {e.source_port.schema_ref} → "
                    f"{e.target_port.schema_ref} ({compat.reason})",
                    edge_id=e.id,
                    fix_hint="Insert a Type Convert component or change the connection.",
                )
            )
            continue
        e.coercion = compat.coercion
        if compat.warning == "W201":
            diags.append(D(DiagnosticCode.W201, WARNING_BY_CODE["W201"], edge_id=e.id))
        elif compat.warning == "W202":
            diags.append(D(DiagnosticCode.W202, WARNING_BY_CODE["W202"], edge_id=e.id))
        elif compat.warning == "W203":
            diags.append(
                D(
                    DiagnosticCode.W203,
                    f"implicit coercion inserted: {compat.coercion}",
                    edge_id=e.id,
                )
            )

    # ---------------------------------------------------------------- routers
    for node in ir.nodes.values():
        if not router_like(node):
            continue
        labels = {name for name, o in node.outputs.items() if o.port.family == PortFamily.ROUTE}
        seen: dict[str, int] = defaultdict(int)
        for e in ir.router_edges():
            if e.spec.source.node == node.id:
                seen[e.spec.source.output] += 1
        for label in labels:
            if seen.get(label, 0) == 0:
                diags.append(
                    D(
                        DiagnosticCode.E022,
                        f"router {node.id!r}: branch {label!r} not covered",
                        node_id=node.id,
                    )
                )
            elif seen[label] > 1:
                diags.append(
                    D(
                        DiagnosticCode.E022,
                        f"router {node.id!r}: duplicate edges for branch {label!r}",
                        node_id=node.id,
                    )
                )

    # ---------------------------------------------------------------- required inputs
    for node in ir.nodes.values():
        connected = {
            e.spec.target.input for e in ir.in_edges(node.id) if e.kind in ("data", "tool")
        }
        for f in node.component.inputs:
            value = node.config.get(f.name, f.default)
            empty = value is None or (isinstance(value, str) and value.strip() == "")
            if not f.required or not empty:
                continue
            if f.as_port is not None or f.port_only:
                if f.name not in connected:
                    diags.append(
                        D(
                            DiagnosticCode.E031,
                            f"required input port {f.name!r} unconnected",
                            node_id=node.id,
                            field=f.name,
                        )
                    )
            else:
                diags.append(
                    D(
                        DiagnosticCode.E010,
                        f"required field {f.name!r} is empty",
                        node_id=node.id,
                        field=f.name,
                    )
                )

    # ---------------------------------------------------------------- graph shape
    start = ir.nodes.get("start")
    terminals = [n for n in ir.nodes.values() if n.kind == NodeKind.TERMINAL]
    if start is None:
        diags.append(D(DiagnosticCode.E030, "flow has no `start` node"))
    if not terminals:
        diags.append(D(DiagnosticCode.E030, "flow has no terminal node (e.g. `end`)"))

    # explicit endpoint rules: `start` must lead somewhere, terminals must be fed
    if start is not None and not any(e.kind in ("data", "router") for e in ir.out_edges("start")):
        diags.append(
            D(
                DiagnosticCode.E030,
                "`start` has no outgoing connection — the flow never leaves it",
                node_id="start",
                fix_hint="Connect start.message (or data/files) to your first node.",
            )
        )
    for terminal in terminals:
        if not any(e.kind in ("data", "router") for e in ir.in_edges(terminal.id)):
            diags.append(
                D(
                    DiagnosticCode.E030,
                    f"terminal node {terminal.id!r} has no inbound connection",
                    node_id=terminal.id,
                    fix_hint="Route a result (message/text/json) into it.",
                )
            )

    succ = _control_successors(ir)
    if start is not None:
        reachable = _reachable(succ, "start")
        if terminals and not any(t.id in reachable for t in terminals):
            diags.append(D(DiagnosticCode.E030, "no terminal node reachable from `start`"))
        tool_only = {
            n.id
            for n in ir.nodes.values()
            if ir.out_edges(n.id)
            and all(e.kind == "tool" for e in ir.out_edges(n.id))
            and not ir.in_edges(n.id)
        }
        for n in ir.nodes.values():
            if n.id not in reachable and n.id not in tool_only:
                diags.append(
                    D(
                        DiagnosticCode.W401,
                        f"node {n.id!r} unreachable from start (dead code)",
                        node_id=n.id,
                    )
                )

        # ---- cycles (E032 / I501)
        for comp in _sccs(list(ir.nodes.keys()), succ):
            is_cycle = len(comp) > 1 or (comp[0] in succ.get(comp[0], ()))
            if not is_cycle:
                continue
            guards = [
                ir.nodes[nid]
                for nid in comp
                if nid in ir.nodes and ir.nodes[nid].kind in (NodeKind.ROUTER, NodeKind.INTERRUPT)
            ]
            cycle_desc = " → ".join(sorted(comp))
            if not guards:
                diags.append(
                    D(
                        DiagnosticCode.E032,
                        f"cycle [{cycle_desc}] contains no router or interrupt node "
                        "(guaranteed infinite loop)",
                        node_id=sorted(comp)[0],
                    )
                )
            else:
                diags.append(
                    D(
                        DiagnosticCode.I501,
                        f"cycle detected [{cycle_desc}] — recursion_limit="
                        f"{ir.spec.flow.settings.recursion_limit} applies",
                        node_id=sorted(comp)[0],
                    )
                )

        # ---- E040: interrupt inside a parallel branch set
        interrupts = {n.id for n in ir.nodes.values() if n.kind == NodeKind.INTERRUPT}
        if interrupts:
            for n in ir.nodes.values():
                if router_like(n):
                    continue  # router branches are exclusive, not parallel
                data_out = [e for e in ir.out_edges(n.id) if e.kind == "data"]
                if len(data_out) < 2:
                    continue
                branch_sets = [_reachable(succ, e.spec.target.node) for e in data_out]
                for i, bs in enumerate(branch_sets):
                    hit = bs & interrupts
                    others = [b for j, b in enumerate(branch_sets) if j != i]
                    if hit and others:
                        for node_id in sorted(hit):
                            diags.append(
                                D(
                                    DiagnosticCode.E040,
                                    f"interrupt node {node_id!r} runs in a parallel "
                                    f"branch set fanned out from {n.id!r} "
                                    "(unsupported in v1)",
                                    node_id=node_id,
                                )
                            )
                        break

    # dedupe identical diagnostics (fan-out checks can repeat)
    seen_keys: set[tuple[DiagnosticCode, str | None, str | None, str | None, str]] = set()
    unique: list[Diagnostic] = []
    for d in diags:
        key = (d.code, d.node_id, d.edge_id, d.field, d.message)
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(d)
    return unique
