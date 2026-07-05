"""Compiler validation — the highest-value test surface (CLAUDE.md §16)."""

from graphforge.compiler.build import validate
from graphforge.compiler.spec import FlowSpec

from .conftest import hitl_flow, simple_flow


def codes(issues):
    return {i.code for i in issues if i.severity == "error"}


def make(nodes, edges, slug="t") -> FlowSpec:
    return FlowSpec(slug=slug, name="t", nodes=nodes, edges=edges)


def test_valid_minimal_flow(loaded_registry):
    assert codes(validate(simple_flow(), loaded_registry)) == set()


def test_cycles_are_allowed(loaded_registry):
    assert codes(validate(hitl_flow(), loaded_registry)) == set()


def test_unknown_component(loaded_registry):
    spec = make(
        [{"id": "a", "component": "does_not_exist"}],
        [{"source": "__start__", "target": "a"}, {"source": "a", "target": "__end__"}],
    )
    assert "unknown_component" in codes(validate(spec, loaded_registry))


def test_component_version_mismatch(loaded_registry):
    spec = make(
        [{"id": "a", "component": "fake_llm", "component_version": 99}],
        [{"source": "__start__", "target": "a"}, {"source": "a", "target": "__end__"}],
    )
    assert "component_version_mismatch" in codes(validate(spec, loaded_registry))


def test_invalid_config_extra_field(loaded_registry):
    spec = make(
        [{"id": "a", "component": "fake_llm", "config": {"nope": 1}}],
        [{"source": "__start__", "target": "a"}, {"source": "a", "target": "__end__"}],
    )
    assert "invalid_config" in codes(validate(spec, loaded_registry))


def test_missing_start_edge(loaded_registry):
    spec = make([{"id": "a", "component": "fake_llm"}], [{"source": "a", "target": "__end__"}])
    result = codes(validate(spec, loaded_registry))
    assert "missing_start" in result
    assert "unreachable_node" in result


def test_multiple_start_edges(loaded_registry):
    spec = make(
        [{"id": "a", "component": "fake_llm"}, {"id": "b", "component": "fake_llm"}],
        [
            {"source": "__start__", "target": "a"},
            {"source": "__start__", "target": "b"},
            {"source": "a", "target": "__end__"},
            {"source": "b", "target": "__end__"},
        ],
    )
    assert "multiple_start" in codes(validate(spec, loaded_registry))


def test_unreachable_node(loaded_registry):
    spec = make(
        [{"id": "a", "component": "fake_llm"}, {"id": "island", "component": "fake_llm"}],
        [{"source": "__start__", "target": "a"}, {"source": "a", "target": "__end__"}],
    )
    assert "unreachable_node" in codes(validate(spec, loaded_registry))


def test_router_output_unwired(loaded_registry):
    spec = hitl_flow()
    spec.edges = [e for e in spec.edges if e.source_handle != "rejected"]
    assert "router_output_unwired" in codes(validate(spec, loaded_registry))


def test_router_unknown_output(loaded_registry):
    spec = hitl_flow()
    for edge in spec.edges:
        if edge.source_handle == "rejected":
            edge.source_handle = "maybe"
    result = codes(validate(spec, loaded_registry))
    assert "unknown_router_output" in result
    assert "router_output_unwired" in result


def test_router_output_wired_twice(loaded_registry):
    spec = hitl_flow()
    spec.edges.append(type(spec.edges[0])(source="review", source_handle="approved", target="llm"))
    assert "router_output_rewired" in codes(validate(spec, loaded_registry))


def test_dangling_handle_on_plain_node(loaded_registry):
    spec = make(
        [{"id": "a", "component": "fake_llm"}],
        [
            {"source": "__start__", "target": "a"},
            {"source": "a", "source_handle": "oops", "target": "__end__"},
        ],
    )
    assert "dangling_handle" in codes(validate(spec, loaded_registry))


def test_multiple_out_edges_on_plain_node(loaded_registry):
    spec = make(
        [{"id": "a", "component": "fake_llm"}, {"id": "b", "component": "fake_llm"}],
        [
            {"source": "__start__", "target": "a"},
            {"source": "a", "target": "b"},
            {"source": "a", "target": "__end__"},
            {"source": "b", "target": "__end__"},
        ],
    )
    assert "multiple_out_edges" in codes(validate(spec, loaded_registry))


def test_attach_rules(loaded_registry):
    # provider -> accepting agent: ok
    spec = make(
        [
            {"id": "agent", "component": "llm_agent"},
            {
                "id": "tools",
                "component": "mcp_toolset",
                "config": {"transport": "streamable_http", "url": "http://x/mcp"},
            },
        ],
        [
            {"source": "__start__", "target": "agent"},
            {"source": "agent", "target": "__end__"},
            {"kind": "attach", "source": "tools", "target": "agent"},
        ],
    )
    assert codes(validate(spec, loaded_registry)) == set()

    # attach into a non-accepting node
    spec_bad = make(
        [
            {"id": "a", "component": "fake_llm"},
            {
                "id": "tools",
                "component": "mcp_toolset",
                "config": {"transport": "streamable_http", "url": "http://x/mcp"},
            },
        ],
        [
            {"source": "__start__", "target": "a"},
            {"source": "a", "target": "__end__"},
            {"kind": "attach", "source": "tools", "target": "a"},
        ],
    )
    assert "attach_not_accepted" in codes(validate(spec_bad, loaded_registry))

    # attach whose source is not a provider
    spec_bad2 = make(
        [
            {"id": "a", "component": "fake_llm"},
            {"id": "agent", "component": "llm_agent"},
        ],
        [
            {"source": "__start__", "target": "agent"},
            {"source": "agent", "target": "__end__"},
            {"kind": "attach", "source": "a", "target": "agent"},
        ],
    )
    result = codes(validate(spec_bad2, loaded_registry))
    assert "attach_source_not_provider" in result


def test_provider_cannot_be_control_flow(loaded_registry):
    spec = make(
        [
            {
                "id": "tools",
                "component": "mcp_toolset",
                "config": {"transport": "streamable_http", "url": "http://x/mcp"},
            },
        ],
        [
            {"source": "__start__", "target": "tools"},
            {"source": "tools", "target": "__end__"},
        ],
    )
    assert "provider_in_control_flow" in codes(validate(spec, loaded_registry))


def test_unused_provider_is_warning_only(loaded_registry):
    spec = simple_flow()
    spec.nodes.append(
        type(spec.nodes[0])(
            id="tools",
            component="mcp_toolset",
            config={"transport": "streamable_http", "url": "http://x/mcp"},
        )
    )
    issues = validate(spec, loaded_registry)
    assert codes(issues) == set()
    assert any(i.code == "unused_provider" and i.severity == "warning" for i in issues)
