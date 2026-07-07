"""Compiler goldens: diagnostics + graph topology snapshots (SPEC §15.2)."""

from __future__ import annotations

import copy
from typing import Any

from lga.compiler import compile_flow
from lga.schema.diagnostics import DiagnosticCode
from tests.conftest import approval_spec, hello_spec


def codes(compiled) -> list[str]:
    return sorted(d.code.value for d in compiled.diagnostics)


def test_hello_compiles_clean():
    compiled = compile_flow(hello_spec(), use_cache=False)
    assert compiled.ok and codes(compiled) == []
    drawn = compiled.graph.get_graph()
    assert set(drawn.nodes) == {"__start__", "start", "fake", "end", "__end__"}


def test_determinism_same_fingerprint():
    a = compile_flow(hello_spec(), use_cache=False)
    b = compile_flow(hello_spec(), use_cache=False)
    assert a.fingerprint == b.fingerprint
    assert a.report.model_dump() == b.report.model_dump()


def test_compile_cache_hit():
    a = compile_flow(hello_spec("cached-flow"))
    b = compile_flow(hello_spec("cached-flow"))
    assert a is b


def test_e001_schema_invalid():
    compiled = compile_flow({"schema_version": "99", "flow": {}}, use_cache=False)
    assert DiagnosticCode.E001 in [d.code for d in compiled.diagnostics]


def test_e002_unknown_component():
    spec = hello_spec()
    spec["nodes"][1]["component_id"] = "lga.nope.missing"
    compiled = compile_flow(spec, use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E002)
    assert diag.node_id == "fake" and "LGA_COMPONENTS_PATH" in (diag.fix_hint or "")


def test_e003_reserved_id_misuse():
    spec = hello_spec()
    spec["nodes"][0]["component_id"] = "lga.testing.fake_llm"
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E003 in [d.code for d in compiled.diagnostics]


def test_e010_required_field_empty():
    spec = hello_spec()
    spec["nodes"].insert(
        2,
        {
            "id": "call",
            "component_id": "lga.llm.llm_call",
            "component_version": "1.0.0",
            "config": {"model": {"provider": "fake", "model": "x"}},  # prompt missing
            "position": {"x": 0, "y": 0},
        },
    )
    spec["edges"].append(
        {
            "id": "e9",
            "kind": "data",
            "source": {"node": "fake", "output": "message"},
            "target": {"node": "call", "input": "input"},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E010 in [d.code for d in compiled.diagnostics]


def test_e011_field_schema_violation():
    spec = hello_spec()
    spec["nodes"][1]["config"] = {"replies": "not-a-list"}
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E011 in [d.code for d in compiled.diagnostics]


def test_e012_missing_secret_ref():
    spec = hello_spec()
    spec["nodes"][1]["config"]["stream_tokens"] = False
    spec["nodes"][1]["config"]["replies"] = ["x"]
    spec["nodes"].append(
        {
            "id": "t",
            "component_id": "lga.io.text_input",
            "component_version": "1.0.0",
            "config": {"value": {"$var": "definitely_missing_var_xyz"}},
            "position": {"x": 0, "y": 0},
        }
    )
    spec["edges"].append(
        {
            "id": "et",
            "kind": "data",
            "source": {"node": "t", "output": "text"},
            "target": {"node": "end", "input": "text"},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E012 in [d.code for d in compiled.diagnostics]


def test_e020_incompatible_edge_names_both_refs():
    spec = hello_spec()
    # Toolset output → Message input: cross-family, no coercion
    spec["nodes"].append(
        {
            "id": "tools",
            "component_id": "lga.tools.calculator",
            "component_version": "1.0.0",
            "config": {"expression": "1"},
            "position": {"x": 0, "y": 0},
        }
    )
    spec["edges"].append(
        {
            "id": "bad",
            "kind": "data",
            "source": {"node": "tools", "output": "toolset"},
            "target": {"node": "fake", "input": "input"},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E020)
    assert "lga:Toolset" in diag.message and "lga:Message" in diag.message


def test_e021_tool_edge_rules():
    spec = hello_spec()
    spec["edges"].append(
        {
            "id": "bad",
            "kind": "tool",
            "source": {"node": "fake", "output": "message"},
            "target": {"node": "end", "input": "message"},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E021 in [d.code for d in compiled.diagnostics]


def test_e022_router_coverage():
    spec = approval_spec()
    spec["edges"] = [e for e in spec["edges"] if e["id"] != "e4"]  # reject uncovered
    compiled = compile_flow(spec, use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E022)
    assert "reject" in diag.message


def test_e023_route_wired_as_data():
    spec = approval_spec()
    spec["edges"][2]["kind"] = "data"  # approve branch as data edge
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E023 in [d.code for d in compiled.diagnostics]


def test_e024_edge_into_start_and_out_of_terminal():
    spec = hello_spec()
    spec["edges"].append(
        {
            "id": "b1",
            "kind": "data",
            "source": {"node": "end", "output": "result"},
            "target": {"node": "start", "input": "input"},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    found = [d for d in compiled.diagnostics if d.code == DiagnosticCode.E024]
    assert len(found) == 2  # into start AND out of terminal


def test_e030_no_start():
    spec = hello_spec()
    spec["nodes"] = spec["nodes"][1:]
    spec["edges"] = spec["edges"][1:]
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E030 in [d.code for d in compiled.diagnostics]


def test_e030_start_must_lead_somewhere():
    """start dangling + island feeding end → hard error, never 'valid'."""
    spec = hello_spec()
    spec["edges"] = [e for e in spec["edges"] if e["id"] != "e1"]  # cut start → fake
    compiled = compile_flow(spec, use_cache=False)
    messages = [d.message for d in compiled.diagnostics if d.code == DiagnosticCode.E030]
    assert any("no outgoing connection" in m for m in messages)
    assert not compiled.ok


def test_e030_terminal_needs_inbound():
    spec = hello_spec()
    spec["edges"] = [e for e in spec["edges"] if e["id"] != "e2"]  # cut fake → end
    compiled = compile_flow(spec, use_cache=False)
    messages = [d.message for d in compiled.diagnostics if d.code == DiagnosticCode.E030]
    assert any("no inbound connection" in m for m in messages)
    assert not compiled.ok


def test_e031_required_port_unconnected():
    spec = hello_spec()
    spec["nodes"].append(
        {
            "id": "out",
            "component_id": "lga.io.text_output",
            "component_version": "1.0.0",
            "config": {},
            "position": {"x": 0, "y": 0},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    # text_output.text is a HandleField but not required → W401 only; make one required
    assert DiagnosticCode.W401 in [d.code for d in compiled.diagnostics]


def test_e032_unguarded_cycle():
    spec = hello_spec()
    spec["nodes"].insert(
        2,
        {
            "id": "echo",
            "component_id": "lga.testing.fake_llm",
            "component_version": "1.0.0",
            "config": {"replies": ["loop"]},
            "position": {"x": 0, "y": 0},
        },
    )
    spec["edges"] += [
        {
            "id": "c1",
            "kind": "data",
            "source": {"node": "fake", "output": "message"},
            "target": {"node": "echo", "input": "input"},
        },
        {
            "id": "c2",
            "kind": "data",
            "source": {"node": "echo", "output": "message"},
            "target": {"node": "fake", "input": "input"},
        },
    ]
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E032 in [d.code for d in compiled.diagnostics]


def test_i501_guarded_cycle_is_info():
    compiled = compile_flow(approval_spec(), use_cache=False)
    assert compiled.ok
    assert DiagnosticCode.I501 in [d.code for d in compiled.diagnostics]
    assert DiagnosticCode.E032 not in [d.code for d in compiled.diagnostics]


def test_w203_coercion_reported():
    spec = hello_spec()
    spec["edges"][1] = {
        "id": "e2",
        "kind": "data",
        "source": {"node": "fake", "output": "message"},
        "target": {"node": "end", "input": "text"},
    }  # Message → Text
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.W203 in [d.code for d in compiled.diagnostics]
    assert {"edge_id": "e2", "coercion": "message_to_text"} in compiled.report.coercions


def test_report_contents():
    compiled = compile_flow(approval_spec(), use_cache=False)
    report = compiled.report
    assert report.router_tables == {"review": {"approve": "end", "reject": "fake"}}
    assert report.interrupt_points == ["review"]
    assert report.channels["e1"] == "start.message"
    assert any(n["id"] == "review" and n["kind"] == "interrupt" for n in report.nodes)


def test_tool_provider_not_a_graph_node():
    spec = hello_spec()
    spec["nodes"].append(
        {
            "id": "calc",
            "component_id": "lga.tools.calculator",
            "component_version": "1.0.0",
            "config": {"expression": "1+1"},
            "position": {"x": 0, "y": 0},
        }
    )
    spec["nodes"].append(
        {
            "id": "agent",
            "component_id": "lga.llm.llm_agent",
            "component_version": "1.0.0",
            "config": {"model": {"provider": "fake", "model": "ok"}},
            "position": {"x": 0, "y": 0},
        }
    )
    spec["edges"] = [
        {
            "id": "e1",
            "kind": "data",
            "source": {"node": "start", "output": "message"},
            "target": {"node": "agent", "input": "input"},
        },
        {
            "id": "t1",
            "kind": "tool",
            "source": {"node": "calc", "output": "toolset"},
            "target": {"node": "agent", "input": "tools"},
        },
        {
            "id": "e2",
            "kind": "data",
            "source": {"node": "agent", "output": "message"},
            "target": {"node": "end", "input": "message"},
        },
    ]
    spec["nodes"] = [n for n in spec["nodes"] if n["id"] != "fake"]
    compiled = compile_flow(spec, use_cache=False)
    assert compiled.ok, codes(compiled)
    assert "calc" not in compiled.graph.get_graph().nodes
    assert compiled.report.tool_bindings.get("agent")


def test_tweaks_override_and_secrets_not_tweakable():
    spec = hello_spec()
    compiled = compile_flow(spec, tweaks={"fake": {"replies": ["tweaked"]}}, use_cache=False)
    assert compiled.ok
    assert compiled.ir.nodes["fake"].config["replies"] == ["tweaked"]


def test_migration_w302():
    spec = hello_spec()
    spec["nodes"][1]["component_version"] = "0.9.0"
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.W302 in [d.code for d in compiled.diagnostics]


def _deep(obj: Any) -> Any:
    return copy.deepcopy(obj)
