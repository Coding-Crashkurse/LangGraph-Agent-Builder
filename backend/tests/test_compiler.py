"""Compiler goldens: diagnostics + graph topology snapshots (SPEC §15.2)."""

from __future__ import annotations

import copy
from typing import Any

from langgraph_agent_builder.compiler import CompiledFlow, compile_flow, validate_flow
from langgraph_agent_builder.schema.diagnostics import DiagnosticCode
from langgraph_agent_builder.schema.state import FlowState
from langgraph_agent_builder.sdk import BuildContext, Component, Output, fields
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.ports import TEXT
from langgraph_agent_builder.sdk.registry import ComponentRegistry, get_registry
from tests.conftest import approval_spec, hello_spec


def codes(compiled: CompiledFlow) -> list[str]:
    return sorted(d.code.value for d in compiled.diagnostics)


class _Vars:
    """Minimal VariablesProvider for cache-key tests."""

    def __init__(
        self, variables: dict[str, str] | None = None, secrets: dict[str, str] | None = None
    ) -> None:
        self._vars = variables or {}
        self._secrets = secrets or {}

    def get_var(self, name: str) -> str | None:
        return self._vars.get(name)

    def get_secret(self, name: str) -> str | None:
        return self._secrets.get(name)

    def has_var(self, name: str) -> bool:
        return name in self._vars

    def has_secret(self, name: str) -> bool:
        return name in self._secrets


def _registry_with(*extra: type[Component]) -> ComponentRegistry:
    registry = ComponentRegistry()
    for cls in get_registry().components.values():
        registry.register(cls, "test")
    for cls in extra:
        registry.register(cls, "test")
    return registry


def test_hello_compiles_clean() -> None:
    compiled = compile_flow(hello_spec(), use_cache=False)
    assert compiled.ok
    assert codes(compiled) == []
    drawn = compiled.graph.get_graph()
    assert set(drawn.nodes) == {"__start__", "start", "fake", "end", "__end__"}


def test_determinism_same_fingerprint() -> None:
    a = compile_flow(hello_spec(), use_cache=False)
    b = compile_flow(hello_spec(), use_cache=False)
    assert a.fingerprint == b.fingerprint
    assert a.report.model_dump() == b.report.model_dump()


def test_compile_cache_hit() -> None:
    a = compile_flow(hello_spec("cached-flow"))
    b = compile_flow(hello_spec("cached-flow"))
    assert a is b


def test_e001_schema_invalid() -> None:
    compiled = compile_flow({"schema_version": "99", "flow": {}}, use_cache=False)
    assert DiagnosticCode.E001 in [d.code for d in compiled.diagnostics]


def test_e002_unknown_component() -> None:
    spec = hello_spec()
    spec["nodes"][1]["component_id"] = "lab.nope.missing"
    compiled = compile_flow(spec, use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E002)
    assert diag.node_id == "fake"
    assert "LAB_COMPONENTS_PATH" in (diag.fix_hint or "")


def test_e003_reserved_id_misuse() -> None:
    spec = hello_spec()
    spec["nodes"][0]["component_id"] = "lab.testing.fake_llm"
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E003 in [d.code for d in compiled.diagnostics]


def test_e010_required_field_empty() -> None:
    spec = hello_spec()
    spec["nodes"].insert(
        2,
        {
            "id": "call",
            "component_id": "lab.llm.llm_call",
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


def test_e011_field_schema_violation() -> None:
    spec = hello_spec()
    spec["nodes"][1]["config"] = {"replies": "not-a-list"}
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E011 in [d.code for d in compiled.diagnostics]


def test_e012_missing_secret_ref() -> None:
    spec = hello_spec()
    spec["nodes"][1]["config"]["stream_tokens"] = False
    spec["nodes"][1]["config"]["replies"] = ["x"]
    spec["nodes"].append(
        {
            "id": "t",
            "component_id": "lab.io.text_input",
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


def test_e014_credential_in_non_secret_field() -> None:
    """A bare $secret assigned to a plain-text field is rejected (SPEC §5.4/§10.5)."""
    spec = hello_spec()
    spec["nodes"].append(
        {
            "id": "t",
            "component_id": "lab.io.text_input",
            "component_version": "1.0.0",
            "config": {"value": {"$secret": "OPENAI_API_KEY"}},  # `value` is not a Secret field
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
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E014)
    assert diag.node_id == "t"
    assert diag.field == "value"


def test_e014_allows_secret_in_secret_field() -> None:
    """A $secret in an actual Secret field (web_search.api_key) does NOT trip E014."""
    spec = hello_spec()
    spec["nodes"].append(
        {
            "id": "ws",
            "component_id": "lab.tools.web_search",
            "component_version": "1.0.0",
            "config": {"api_key": {"$secret": "TAVILY_KEY"}},  # api_key IS a SecretInput
            "position": {"x": 0, "y": 0},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E014 not in [d.code for d in compiled.diagnostics]


# ------------------------------------------------------------------ $resource (Resources layer)
class _ResourceConsumer(Component):
    component_id = "test.compiler.resource_consumer"
    display_name = "Resource Consumer"
    category = "testing"
    inputs = [
        fields.StrInput(name="input", as_port=TEXT),
        fields.ResourceRefInput(name="provider", resource_type="model_provider"),
    ]
    outputs = [Output(name="message", port=TEXT)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {"message": ""}

        return node


def _resource_spec(slug: str, value: Any) -> dict[str, Any]:
    spec = hello_spec(slug)
    spec["nodes"][1]["component_id"] = _ResourceConsumer.component_id
    spec["nodes"][1]["config"] = {"provider": value}
    return spec


def test_e016_unknown_resource() -> None:
    registry = _registry_with(_ResourceConsumer)
    compiled = compile_flow(
        _resource_spec("res-e016", {"$resource": "ghost"}),
        registry=registry,
        resources={},
        use_cache=False,
    )
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E016)
    assert diag.node_id == "fake"
    assert diag.field == "provider"
    assert "ghost" in diag.message


def test_e017_resource_type_mismatch() -> None:
    registry = _registry_with(_ResourceConsumer)
    compiled = compile_flow(
        _resource_spec("res-e017", {"$resource": "kb1"}),
        registry=registry,
        resources={"kb1": "knowledge_base#deadbeef"},
        use_cache=False,
    )
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E017)
    assert "knowledge_base" in diag.message
    assert "model_provider" in diag.message


def test_resource_ref_resolves_to_handle() -> None:
    from langgraph_agent_builder.sdk.ports import ResourceHandle

    registry = _registry_with(_ResourceConsumer)
    compiled = compile_flow(
        _resource_spec("res-ok", {"$resource": "gpt", "model": "gpt-4o"}),
        registry=registry,
        resources={"gpt": "model_provider#deadbeef"},
        use_cache=False,
    )
    assert compiled.ok, codes(compiled)
    handle = compiled.node_contexts["fake"].get_field("provider")
    assert isinstance(handle, ResourceHandle)
    assert handle.name == "gpt"
    assert handle.resource_type == "model_provider"
    assert handle.payload == {"model": "gpt-4o"}


def test_e020_incompatible_edge_names_both_refs() -> None:
    spec = hello_spec()
    # Toolset output → Message input: cross-family, no coercion
    spec["nodes"].append(
        {
            "id": "tools",
            "component_id": "lab.tools.calculator",
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
    assert "lab:Toolset" in diag.message
    assert "lab:Message" in diag.message


def test_e021_tool_edge_rules() -> None:
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


def test_e022_router_coverage() -> None:
    spec = approval_spec()
    spec["edges"] = [e for e in spec["edges"] if e["id"] != "e4"]  # reject uncovered
    compiled = compile_flow(spec, use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E022)
    assert "reject" in diag.message


def test_e023_route_wired_as_data() -> None:
    spec = approval_spec()
    spec["edges"][2]["kind"] = "data"  # approve branch as data edge
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E023 in [d.code for d in compiled.diagnostics]


def test_e024_edge_into_start_and_out_of_terminal() -> None:
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


def test_e030_no_start() -> None:
    spec = hello_spec()
    spec["nodes"] = spec["nodes"][1:]
    spec["edges"] = spec["edges"][1:]
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.E030 in [d.code for d in compiled.diagnostics]


def test_e030_start_must_lead_somewhere() -> None:
    """start dangling + island feeding end → hard error, never 'valid'."""
    spec = hello_spec()
    spec["edges"] = [e for e in spec["edges"] if e["id"] != "e1"]  # cut start → fake
    compiled = compile_flow(spec, use_cache=False)
    messages = [d.message for d in compiled.diagnostics if d.code == DiagnosticCode.E030]
    assert any("no outgoing connection" in m for m in messages)
    assert not compiled.ok


def test_e030_terminal_needs_inbound() -> None:
    spec = hello_spec()
    spec["edges"] = [e for e in spec["edges"] if e["id"] != "e2"]  # cut fake → end
    compiled = compile_flow(spec, use_cache=False)
    messages = [d.message for d in compiled.diagnostics if d.code == DiagnosticCode.E030]
    assert any("no inbound connection" in m for m in messages)
    assert not compiled.ok


def test_e031_required_port_unconnected() -> None:
    spec = hello_spec()
    spec["nodes"].append(
        {
            "id": "out",
            "component_id": "lab.io.text_output",
            "component_version": "1.0.0",
            "config": {},
            "position": {"x": 0, "y": 0},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    # text_output.text is a HandleField but not required → W401 only; make one required
    assert DiagnosticCode.W401 in [d.code for d in compiled.diagnostics]


def test_e032_unguarded_cycle() -> None:
    spec = hello_spec()
    spec["nodes"].insert(
        2,
        {
            "id": "echo",
            "component_id": "lab.testing.fake_llm",
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


def test_i501_guarded_cycle_is_info() -> None:
    compiled = compile_flow(approval_spec(), use_cache=False)
    assert compiled.ok
    assert DiagnosticCode.I501 in [d.code for d in compiled.diagnostics]
    assert DiagnosticCode.E032 not in [d.code for d in compiled.diagnostics]


def test_w203_coercion_reported() -> None:
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


def test_report_contents() -> None:
    compiled = compile_flow(approval_spec(), use_cache=False)
    report = compiled.report
    assert report.router_tables == {"review": {"approve": "end", "reject": "fake"}}
    assert report.interrupt_points == ["review"]
    assert report.channels["e1"] == "start.message"
    assert any(n["id"] == "review" and n["kind"] == "interrupt" for n in report.nodes)


def test_tool_provider_not_a_graph_node() -> None:
    spec = hello_spec()
    spec["nodes"].append(
        {
            "id": "calc",
            "component_id": "lab.tools.calculator",
            "component_version": "1.0.0",
            "config": {"expression": "1+1"},
            "position": {"x": 0, "y": 0},
        }
    )
    spec["nodes"].append(
        {
            "id": "agent",
            "component_id": "lab.llm.llm_agent",
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


def test_tweaks_override_and_secrets_not_tweakable() -> None:
    spec = hello_spec()
    compiled = compile_flow(spec, tweaks={"fake": {"replies": ["tweaked"]}}, use_cache=False)
    assert compiled.ok
    assert compiled.ir is not None
    assert compiled.ir.nodes["fake"].config["replies"] == ["tweaked"]


def test_migration_w302() -> None:
    spec = hello_spec()
    spec["nodes"][1]["component_version"] = "0.9.0"
    compiled = compile_flow(spec, use_cache=False)
    assert DiagnosticCode.W302 in [d.code for d in compiled.diagnostics]


# ------------------------------------------------------------------ cache soundness
def test_compile_cache_missed_when_variable_changes() -> None:
    """Editing a global variable must never serve a stale cached compile."""
    spec = hello_spec("cache-vars")
    spec["nodes"][1]["config"]["greeting"] = {"$var": "g"}
    a = compile_flow(spec, variables=_Vars(variables={"g": "one"}))
    b = compile_flow(spec, variables=_Vars(variables={"g": "one"}))
    c = compile_flow(spec, variables=_Vars(variables={"g": "two"}))
    assert a is b  # identical snapshot → cache hit
    assert c is not a
    assert c.ir is not None
    assert c.ir.nodes["fake"].config["greeting"] == "two"


def test_compile_cache_missed_when_secret_rotates() -> None:
    spec = hello_spec("cache-secrets")
    spec["nodes"].append(
        {
            "id": "ws",
            "component_id": "lab.tools.web_search",
            "component_version": "1.0.0",
            "config": {"query": "x", "api_key": {"$secret": "K"}},
            "position": {"x": 0, "y": 0},
        }
    )
    a = compile_flow(spec, variables=_Vars(secrets={"K": "sk-old"}))
    b = compile_flow(spec, variables=_Vars(secrets={"K": "sk-new"}))
    assert b is not a  # rotated secret → recompile, old plaintext gone
    assert b.ir is not None
    assert str(b.ir.nodes["ws"].config["api_key"]) == "sk-new"


def test_compile_cache_includes_tweaks() -> None:
    spec = hello_spec("cache-tweaks")
    a = compile_flow(spec, tweaks={"fake": {"replies": ["one"]}})
    b = compile_flow(spec, tweaks={"fake": {"replies": ["one"]}})
    c = compile_flow(spec, tweaks={"fake": {"replies": ["two"]}})
    assert a is b
    assert c is not a
    assert c.ir is not None
    assert c.ir.nodes["fake"].config["replies"] == ["two"]


# ------------------------------------------------------------------ E015 / validate-only
class _BuildBoom(Component):
    component_id = "test.compiler.build_boom"
    display_name = "Build Boom"
    category = "testing"
    inputs = [fields.StrInput(name="input", as_port=TEXT)]
    outputs = [Output(name="message", port=TEXT)]
    built = 0

    def build(self, ctx: BuildContext) -> NodeFn:
        type(self).built += 1
        raise ValueError("boom: invalid config combination")


def _boom_spec(slug: str) -> dict[str, Any]:
    spec = hello_spec(slug)
    spec["nodes"][1]["component_id"] = _BuildBoom.component_id
    spec["nodes"][1]["config"] = {}
    return spec


def test_e015_build_failure_becomes_diagnostic() -> None:
    """A raising build() is an ERROR diagnostic, not an escaping exception (§5.4)."""
    registry = _registry_with(_BuildBoom)
    compiled = compile_flow(_boom_spec("boom-e015"), registry=registry, use_cache=False)
    assert not compiled.ok
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E015)
    assert diag.node_id == "fake"
    assert "boom" in diag.message


def test_validate_only_never_executes_build() -> None:
    """validate_flow stops after P3 — component code must not run (§5.3)."""
    registry = _registry_with(_BuildBoom)
    _BuildBoom.built = 0
    diags = validate_flow(_boom_spec("boom-validate"), registry=registry)
    assert _BuildBoom.built == 0
    assert not [d for d in diags if d.severity == "error"]


# ------------------------------------------------------------------ Output.method (§4.5)
class _MultiOut(Component):
    component_id = "test.compiler.multi_out"
    display_name = "Multi Out"
    category = "testing"
    inputs = [fields.StrInput(name="input", as_port=TEXT)]
    outputs = [
        Output(name="message", port=TEXT),
        Output(name="upper", port=TEXT, method="compute_upper"),
        Output(name="length", port=TEXT, method="compute_length"),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {"message": "from-nodefn"}

        return node

    def compute_upper(self, state: dict[str, Any], config: Any) -> str:
        return str(state.get("run_meta", {}).get("input_text", "")).upper()

    async def compute_length(self, state: dict[str, Any], config: Any) -> str:
        return str(len(str(state.get("run_meta", {}).get("input_text", ""))))


async def test_output_method_dispatch() -> None:
    """Outputs naming a method are computed by it — sync or async (§4.5 MUST)."""
    from langchain_core.messages import HumanMessage

    registry = _registry_with(_MultiOut)
    spec = hello_spec("method-dispatch")
    spec["nodes"][1]["component_id"] = _MultiOut.component_id
    spec["nodes"][1]["config"] = {}
    compiled = compile_flow(spec, registry=registry, use_cache=False)
    assert compiled.ok, codes(compiled)
    state: FlowState = {
        "messages": [HumanMessage("hi")],
        "ports": {},
        "route": {},
        "run_meta": {"input_text": "hi", "run_id": "t", "thread_id": "t"},
    }
    result = await compiled.graph.ainvoke(state)
    assert result["ports"]["fake.message"] == "from-nodefn"  # returned-dict path intact
    assert result["ports"]["fake.upper"] == "HI"  # sync method
    assert result["ports"]["fake.length"] == "2"  # async method


class _BadMethod(Component):
    component_id = "test.compiler.bad_method"
    display_name = "Bad Method"
    category = "testing"
    inputs = [fields.StrInput(name="input", as_port=TEXT)]
    outputs = [Output(name="message", port=TEXT, method="does_not_exist")]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node


def test_output_method_missing_is_e015() -> None:
    registry = _registry_with(_BadMethod)
    spec = hello_spec("method-missing")
    spec["nodes"][1]["component_id"] = _BadMethod.component_id
    spec["nodes"][1]["config"] = {}
    compiled = compile_flow(spec, registry=registry, use_cache=False)
    assert not compiled.ok
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E015)
    assert diag.node_id == "fake"


def test_e014_nested_secret_ref_is_caught() -> None:
    """The credential-leak guard recurses into containers (SPEC §5.4/§10.5)."""
    spec = hello_spec()
    spec["nodes"].append(
        {
            "id": "t",
            "component_id": "lab.io.text_input",
            "component_version": "1.0.0",
            "config": {"value": {"headers": {"auth": {"$secret": "OPENAI_KEY"}}}},
            "position": {"x": 0, "y": 0},
        }
    )
    compiled = compile_flow(spec, use_cache=False)
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E014)
    assert diag.node_id == "t"
    assert diag.field == "value"


def _deep(obj: Any) -> Any:
    return copy.deepcopy(obj)
