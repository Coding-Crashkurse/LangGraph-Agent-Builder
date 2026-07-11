"""Unit tests for compiler.subgraph ("Run to node" induced subgraphs, §6.4)."""

from __future__ import annotations

import pytest

from langgraph_agent_builder.compiler import compile_flow
from langgraph_agent_builder.compiler.subgraph import ancestors_of, induce_subgraph
from langgraph_agent_builder.runtime.executor import run_compiled_once
from langgraph_agent_builder.schema.diagnostics import DiagnosticCode
from tests.conftest import approval_spec, hello_spec


def test_ancestors_of_includes_self_and_upstream() -> None:
    compiled = compile_flow(hello_spec(), use_cache=False)
    assert compiled.ir is not None
    assert ancestors_of(compiled.ir, "end") == {"start", "fake", "end"}
    assert ancestors_of(compiled.ir, "fake") == {"start", "fake"}
    assert ancestors_of(compiled.ir, "start") == {"start"}


def test_ancestors_of_handles_cycles_without_infinite_loop() -> None:
    # approval flow has a guarded cycle (review --reject--> fake --> review);
    # traversal must dedupe already-seen nodes rather than loop forever.
    compiled = compile_flow(approval_spec(), use_cache=False)
    assert compiled.ir is not None
    assert ancestors_of(compiled.ir, "end") == {"start", "fake", "review", "end"}


def test_induce_subgraph_prunes_downstream_nodes() -> None:
    compiled = compile_flow(hello_spec(), use_cache=False)
    pruned = induce_subgraph(compiled, "fake")
    assert pruned.ir is not None
    assert set(pruned.ir.nodes) == {"start", "fake"}
    assert [e.id for e in pruned.ir.edges] == ["e1"]  # e2 (fake→end) dropped
    graph_nodes = pruned.graph.get_graph().nodes
    assert "end" not in graph_nodes
    assert "fake" in graph_nodes


def test_induce_subgraph_fingerprint_suffix() -> None:
    compiled = compile_flow(hello_spec(), use_cache=False)
    pruned = induce_subgraph(compiled, "fake")
    assert pruned.fingerprint == f"{compiled.fingerprint}:until:fake"
    assert pruned.node_contexts is compiled.node_contexts  # contexts reused, no re-resolve


def test_induce_subgraph_unknown_node_raises_keyerror() -> None:
    compiled = compile_flow(hello_spec(), use_cache=False)
    with pytest.raises(KeyError, match="nope"):
        induce_subgraph(compiled, "nope")


async def test_induced_subgraph_executes_to_terminal_node() -> None:
    compiled = compile_flow(hello_spec(), use_cache=False)
    pruned = induce_subgraph(compiled, "fake")
    out = await run_compiled_once(pruned, input_text="hello")
    assert out["status"] == "completed"


def test_induced_subgraph_report_describes_pruned_graph() -> None:
    """Debug mode renders the report (§5.3) — it must match the induced graph,
    not the full parent topology."""
    compiled = compile_flow(hello_spec(), use_cache=False)
    pruned = induce_subgraph(compiled, "fake")
    assert {n["id"] for n in pruned.report.nodes} == {"start", "fake"}
    assert list(pruned.report.channels) == ["e1"]  # e2 (fake→end) pruned
    assert pruned.report.fingerprint == pruned.fingerprint
    # parent report untouched
    assert {n["id"] for n in compiled.report.nodes} == {"start", "fake", "end"}


def test_induced_subgraph_diagnostics_scoped_to_kept_nodes() -> None:
    spec = hello_spec()
    spec["nodes"].append(
        {
            "id": "island",
            "component_id": "lab.io.text_output",
            "component_version": "1.0.0",
            "config": {},
            "position": {"x": 0, "y": 0},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    assert any(
        d.code == DiagnosticCode.W401 and d.node_id == "island" for d in compiled.diagnostics
    )
    pruned = induce_subgraph(compiled, "fake")
    assert all(d.node_id != "island" for d in pruned.diagnostics)  # pruned node's diag dropped
