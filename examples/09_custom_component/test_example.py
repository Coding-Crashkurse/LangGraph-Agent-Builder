import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent / "pkg" / "src"))

HERE = Path(__file__).parent


def _registry():
    import lga_ticket_triage

    from lga.sdk.registry import ComponentRegistry, get_registry

    registry = ComponentRegistry()
    for cls in get_registry().components.values():
        registry.register(cls, "builtin")
    registry._register_module(lga_ticket_triage, "example-09")
    return registry


def _spec(edges):
    return {
        "schema_version": "1",
        "flow": {"name": "triage", "slug": "triage", "description": "x"},
        "nodes": [
            {"id": "start", "component_id": "lga.io.start", "component_version": "1.0.0",
             "config": {}, "position": {"x": 0, "y": 0}},
            {"id": "parse", "component_id": "ticket_triage.data.ticket_parser",
             "component_version": "1.0.0", "config": {}, "position": {"x": 0, "y": 0}},
            {"id": "summary", "component_id": "ticket_triage.data.ticket_summary",
             "component_version": "1.0.0", "config": {}, "position": {"x": 0, "y": 0}},
            {"id": "end", "component_id": "lga.io.end", "component_version": "1.0.0",
             "config": {}, "position": {"x": 0, "y": 0}},
        ],
        "edges": edges,
    }


GOOD_EDGES = [
    {"id": "e1", "kind": "data", "source": {"node": "start", "output": "message"},
     "target": {"node": "parse", "input": "text"}},
    {"id": "e2", "kind": "data", "source": {"node": "parse", "output": "batch"},
     "target": {"node": "summary", "input": "batch"}},
    {"id": "e3", "kind": "data", "source": {"node": "summary", "output": "text"},
     "target": {"node": "end", "input": "text"}},
]


def test_custom_components_register_and_run():
    import asyncio

    from lga.compiler import compile_flow
    from lga.runtime.executor import run_compiled_once

    compiled = compile_flow(_spec(GOOD_EDGES), registry=_registry(), use_cache=False)
    errors = [d for d in compiled.diagnostics if d.severity == "error"]
    assert not errors, [d.message for d in errors]
    outcome = asyncio.run(
        run_compiled_once(compiled, input_text="printer on fire, urgent!\nnew keyboard")
    )
    assert outcome["result_text"] == "2 tickets (1 high priority)"


def test_e020_names_both_custom_schema_refs():
    from lga.compiler import compile_flow
    from lga.schema.diagnostics import DiagnosticCode

    bad = [
        GOOD_EDGES[0],
        # TicketBatch → Message input: structurally incompatible
        {"id": "bad", "kind": "data", "source": {"node": "parse", "output": "batch"},
         "target": {"node": "end", "input": "message"}},
    ]
    compiled = compile_flow(_spec(bad), registry=_registry(), use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E020)
    assert "ticket_triage:TicketBatch" in diag.message
    assert "lga:Message" in diag.message
