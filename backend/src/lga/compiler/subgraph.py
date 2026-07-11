"""Partial-run induced subgraphs (SPEC §6.4) — "Run to node".

From the same resolved IR, build the induced subgraph of ``until_node`` and all
its ancestors; ``until_node`` becomes the terminal. Reuses the parent compile's
node contexts, so no re-resolve/re-validate is needed.
"""

from __future__ import annotations

from lga.compiler import CompiledFlow, build_report
from lga.compiler import emit as emit_pass
from lga.compiler.ir import FlowIR


def ancestors_of(ir: FlowIR, node_id: str) -> set[str]:
    """All nodes that can reach ``node_id`` (inclusive), over any edge kind."""
    keep: set[str] = set()
    stack = [node_id]
    while stack:
        current = stack.pop()
        if current in keep:
            continue
        keep.add(current)
        for edge in ir.in_edges(current):
            stack.append(edge.spec.source.node)
    return keep


def induce_subgraph(compiled: CompiledFlow, until_node: str) -> CompiledFlow:
    """Return a CompiledFlow whose graph terminates at ``until_node`` (§6.4)."""
    if compiled.ir is None or until_node not in compiled.ir.nodes:
        raise KeyError(f"unknown until_node {until_node!r}")
    ir = compiled.ir
    keep = ancestors_of(ir, until_node)
    pruned = FlowIR(spec=ir.spec)
    pruned.nodes = {nid: ir.nodes[nid] for nid in keep}
    pruned.edges = [
        e for e in ir.edges if e.spec.source.node in keep and e.spec.target.node in keep
    ]
    builder, diagnostics = emit_pass.emit(pruned, compiled.node_contexts)
    fingerprint = f"{compiled.fingerprint}:until:{until_node}"
    # parent diagnostics scoped to the induced subgraph (flow-level ones kept)
    kept_edges = {e.id for e in pruned.edges}
    diagnostics = [
        d
        for d in compiled.diagnostics
        if (d.node_id is None and d.edge_id is None) or d.node_id in keep or d.edge_id in kept_edges
    ] + diagnostics
    return CompiledFlow(
        spec=compiled.spec,
        diagnostics=diagnostics,
        report=build_report(pruned, compiled.node_contexts, fingerprint),
        builder=builder,
        ir=pruned,
        node_contexts=compiled.node_contexts,
        fingerprint=fingerprint,
    )
