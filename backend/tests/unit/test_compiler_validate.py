"""Unit tests for langgraph_agent_builder.compiler.validate (P3): edge/router/port/graph-shape
diagnostics that the goldens in tests/test_compiler.py do not already pin."""

from __future__ import annotations

import copy
from typing import Any

from langgraph_agent_builder.compiler import CompiledFlow, compile_flow
from langgraph_agent_builder.schema.diagnostics import DiagnosticCode
from langgraph_agent_builder.sdk import BuildContext, Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.registry import ComponentRegistry, get_registry
from tests.conftest import approval_spec, hello_spec


def _codes(compiled: CompiledFlow) -> list[DiagnosticCode]:
    return [d.code for d in compiled.diagnostics]


class _NeedsPort(Component):
    """Two input ports; ``must`` is a required port left unwired to trip E031."""

    component_id = "test.needs_port"
    display_name = "Needs Port"
    category = "testing"
    inputs = [
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
        fields.HandleField(
            name="model", display_name="Model", as_port=ports.MESSAGE, required=True
        ),
    ]
    outputs = [Output(name="message", display_name="Message", port=ports.MESSAGE)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node


def _registry_with(*extra: type[Component]) -> ComponentRegistry:
    registry = ComponentRegistry()
    for cls in get_registry().components.values():
        registry.register(cls, "test")
    for cls in extra:
        registry.register(cls, "test")
    return registry


def test_router_edge_from_non_router_node_is_e023() -> None:
    spec = hello_spec()
    # a plain data node (fake) cannot emit a router edge
    spec["edges"].append(
        {
            "id": "r1",
            "kind": "router",
            "source": {"node": "fake", "output": "message"},
            "target": {"node": "end", "input": "result"},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E023)
    assert "non-router" in diag.message


def test_router_edge_unknown_branch_is_e022() -> None:
    spec = approval_spec()
    # review is a real router, but "maybe" is not one of its branches
    spec["edges"].append(
        {
            "id": "r-bad",
            "kind": "router",
            "source": {"node": "review", "output": "maybe"},
            "target": {"node": "end", "input": "result"},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E022 in _codes(compiled)
    assert any("maybe" in d.message for d in compiled.diagnostics)


def test_duplicate_router_branch_edges_is_e022() -> None:
    spec = approval_spec()
    dup = copy.deepcopy(next(e for e in spec["edges"] if e["id"] == "e3"))  # approve branch
    dup["id"] = "e3b"
    spec["edges"].append(dup)
    compiled = compile_flow(spec, use_cache=False)
    assert any(
        d.code == DiagnosticCode.E022 and "duplicate" in d.message for d in compiled.diagnostics
    )


def test_unknown_output_on_data_edge_is_e020() -> None:
    spec = hello_spec()
    spec["edges"][1]["source"]["output"] = "ghost_out"  # fake has no such output
    compiled = compile_flow(spec, use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E020)
    assert "unknown output" in diag.message
    assert "ghost_out" in diag.message


def test_unknown_input_on_data_edge_is_e020() -> None:
    spec = hello_spec()
    spec["edges"][1]["target"]["input"] = "ghost_in"  # end has no such input
    compiled = compile_flow(spec, use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E020)
    assert "unknown input" in diag.message
    assert "ghost_in" in diag.message


def test_any_typed_edge_warns_w201() -> None:
    spec = hello_spec()
    # Set Data exposes an ANY trigger port → connecting anything warns W201
    spec["nodes"].append(
        {
            "id": "sink",
            "component_id": "lab.io.set_data",
            "component_version": "1.0.0",
            "config": {"entries": [{"key": "k", "template": "v"}]},
            "position": {"x": 0, "y": 0},
        }
    )
    spec["edges"].append(
        {
            "id": "anyedge",
            "kind": "data",
            "source": {"node": "start", "output": "message"},
            "target": {"node": "sink", "input": "input"},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.W201 in _codes(compiled)


def test_required_input_port_unconnected_is_e031() -> None:
    spec = hello_spec()
    # _NeedsPort.model is a required MESSAGE port; leave it unwired (input is wired)
    spec["nodes"].append(
        {
            "id": "agent",
            "component_id": _NeedsPort.component_id,
            "component_version": "1.0.0",
            "config": {},
            "position": {"x": 0, "y": 0},
        }
    )
    spec["edges"].append(
        {
            "id": "a-in",
            "kind": "data",
            "source": {"node": "start", "output": "message"},
            "target": {"node": "agent", "input": "input"},
        }
    )
    compiled = compile_flow(spec, registry=_registry_with(_NeedsPort), use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E031)
    assert diag.node_id == "agent"
    assert diag.field == "model"


def test_flow_without_terminal_is_e030() -> None:
    spec = hello_spec()
    spec["nodes"] = [n for n in spec["nodes"] if n["id"] != "end"]
    spec["edges"] = [e for e in spec["edges"] if e["id"] != "e2"]
    compiled = compile_flow(spec, use_cache=False)
    messages = [d.message for d in compiled.diagnostics if d.code == DiagnosticCode.E030]
    assert any("no terminal node" in m for m in messages)


def test_interrupt_in_parallel_branch_is_e040() -> None:
    """An interrupt reachable inside a fan-out branch set is unsupported (E040)."""
    spec: dict[str, Any] = {
        "schema_version": "1",
        "flow": {"name": "par", "slug": "par"},
        "nodes": [
            {
                "id": "start",
                "component_id": "lab.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "fan",
                "component_id": "lab.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["a"]},
                "position": {"x": 100, "y": 0},
            },
            {
                "id": "review",
                "component_id": "lab.flow.human_approval",
                "component_version": "1.0.0",
                "config": {"prompt": "ok?"},
                "position": {"x": 200, "y": 0},
            },
            {
                "id": "other",
                "component_id": "lab.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["b"]},
                "position": {"x": 200, "y": 100},
            },
            {
                "id": "end",
                "component_id": "lab.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 400, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "s",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "fan", "input": "input"},
            },
            # fan-out: fan.message feeds BOTH review (interrupt) and other (parallel)
            {
                "id": "f1",
                "kind": "data",
                "source": {"node": "fan", "output": "message"},
                "target": {"node": "review", "input": "input"},
            },
            {
                "id": "f2",
                "kind": "data",
                "source": {"node": "fan", "output": "message"},
                "target": {"node": "other", "input": "input"},
            },
            {
                "id": "app",
                "kind": "router",
                "source": {"node": "review", "output": "approve"},
                "target": {"node": "end", "input": "result"},
            },
            {
                "id": "rej",
                "kind": "router",
                "source": {"node": "review", "output": "reject"},
                "target": {"node": "other", "input": "input"},
            },
            {
                "id": "o",
                "kind": "data",
                "source": {"node": "other", "output": "message"},
                "target": {"node": "end", "input": "result"},
            },
        ],
    }
    compiled = compile_flow(spec, use_cache=False)
    e040 = [d for d in compiled.diagnostics if d.code == DiagnosticCode.E040]
    assert e040
    assert e040[0].node_id == "review"
