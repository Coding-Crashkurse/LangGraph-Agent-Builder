"""Unit tests for lga.compiler.subgraph ("Run to node" induced subgraphs, §6.4)."""

from __future__ import annotations

import pytest

from lga.compiler import compile_flow
from lga.compiler.subgraph import ancestors_of, induce_subgraph
from lga.runtime.executor import run_compiled_once
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
