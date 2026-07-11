"""Unit tests for the bounded ``{{ }}`` expression language (SPEC §10.5).

Covers ``sdk.expressions`` (render/typed-vs-string/whitelist), the ``Field``
opt-in + Secret guard, the ``BuildContext`` runtime wiring, the compiler's
E018/W205 diagnostics and the new string→number edge coercion (W203).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from jinja2 import TemplateError
from langchain_core.messages import AIMessage, HumanMessage

from langgraph_agent_builder.compiler import compile_flow
from langgraph_agent_builder.schema.diagnostics import DiagnosticCode, Severity
from langgraph_agent_builder.sdk import BuildContext, Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.expressions import (
    WHITELIST,
    has_expression,
    render_expression,
    state_excerpt,
)
from langgraph_agent_builder.sdk.ports import (
    TEXT,
    PortFamily,
    PortSpec,
    check_compatibility,
    coerce,
)
from langgraph_agent_builder.sdk.registry import ComponentRegistry, get_registry
from langgraph_agent_builder.sdk.testing import ComponentTestHarness

SCOPE: dict[str, Any] = {
    "input": {
        "title": "hello",
        "count": 2.4,
        "items": [1, 2, 3],
        "user": {"email": "a@b.co"},
    },
    "state": {"messages": [], "data": {"k": "v"}, "vars": {}},
    "vars": {"env": "prod"},
}


# ------------------------------------------------------------------ has_expression
def test_has_expression_detects_delimiter() -> None:
    assert has_expression("{{ x }}") is True
    assert has_expression("plain") is False
    assert has_expression("{{ unclosed") is True  # typo → still flagged (E018 later)
    assert has_expression(42) is False


# --------------------------------------------------------------- render: modes
def test_no_expression_returned_unchanged() -> None:
    assert render_expression("just a literal", SCOPE) == "just a literal"


def test_path_access() -> None:
    assert render_expression("{{ input.user.email }}", SCOPE) == "a@b.co"


def test_typed_single_expression_preserves_type() -> None:
    result = render_expression("{{ input.items }}", SCOPE)
    assert result == [1, 2, 3]
    assert isinstance(result, list)


def test_mixed_string_template_returns_string() -> None:
    assert render_expression("Hi {{ input.title }}!", SCOPE) == "Hi hello!"


def test_two_blocks_are_a_string_template() -> None:
    assert render_expression("{{ input.title }}-{{ vars.env }}", SCOPE) == "hello-prod"


def test_missing_path_is_none() -> None:
    assert render_expression("{{ input.nope }}", SCOPE) is None
    assert render_expression("{{ input.a.b.c }}", SCOPE) is None


def test_pipes_chain() -> None:
    assert render_expression('{{ input.title | upper | default("-") }}', SCOPE) == "HELLO"


# ------------------------------------------------------- render: each whitelisted fn
def test_now_returns_datetime() -> None:
    assert isinstance(render_expression("{{ now() }}", SCOPE), dt.datetime)


def test_today_returns_date() -> None:
    result = render_expression("{{ today() }}", SCOPE)
    assert isinstance(result, dt.date)


def test_upper_lower() -> None:
    assert render_expression("{{ input.title | upper }}", SCOPE) == "HELLO"
    assert render_expression('{{ "ABC" | lower }}', SCOPE) == "abc"


def test_trim() -> None:
    assert render_expression('{{ "  x  " | trim }}', SCOPE) == "x"


def test_length() -> None:
    assert render_expression("{{ input.items | length }}", SCOPE) == 3


def test_default_fills_missing() -> None:
    assert render_expression('{{ input.nope | default("fallback") }}', SCOPE) == "fallback"


def test_round_returns_number() -> None:
    result = render_expression("{{ input.count | round }}", SCOPE)
    assert result == 2
    assert isinstance(result, (int, float))


def test_json_parse_and_dump_roundtrip() -> None:
    parsed = render_expression("{{ '{\"a\": 1}' | json_parse }}", SCOPE)
    assert parsed == {"a": 1}
    dumped = render_expression("{{ input.user | json_dump }}", SCOPE)
    assert dumped == '{"email": "a@b.co"}'
    assert render_expression("{{ input.user | json_dump | json_parse }}", SCOPE) == {
        "email": "a@b.co"
    }


def test_split_and_join() -> None:
    assert render_expression('{{ "a,b,c" | split(",") }}', SCOPE) == ["a", "b", "c"]
    assert render_expression('{{ input.items | join("-") }}', SCOPE) == "1-2-3"


def test_regex_extract() -> None:
    assert render_expression('{{ "order-42" | regex_extract("[0-9]+") }}', SCOPE) == "42"
    assert render_expression('{{ "no digits" | regex_extract("[0-9]+") }}', SCOPE) is None


def test_replace() -> None:
    assert render_expression('{{ "a-b-c" | replace("-", "_") }}', SCOPE) == "a_b_c"


# ---------------------------------------------------------------- whitelist closed
def test_whitelist_has_exactly_fourteen_names() -> None:
    assert WHITELIST == {
        "now",
        "today",
        "upper",
        "lower",
        "trim",
        "length",
        "default",
        "join",
        "replace",
        "round",
        "json_parse",
        "json_dump",
        "split",
        "regex_extract",
    }
    assert len(WHITELIST) == 14


def test_non_whitelisted_filter_is_rejected() -> None:
    # `capitalize` is a jinja built-in but NOT on the whitelist → hard error.
    with pytest.raises(TemplateError):
        render_expression("{{ input.title | capitalize }}", SCOPE)


# ------------------------------------------------------------------ state_excerpt
def test_state_excerpt_exposes_only_safe_keys() -> None:
    excerpt = state_excerpt(
        {
            "messages": [HumanMessage(content="hi"), AIMessage(content="yo")],
            "data": {"k": "v"},
            "vars": {"a": 1},
            "ports": {"secret.out": "leak"},
            "route": {"n": "b"},
        }
    )
    assert set(excerpt) == {"messages", "data", "vars"}
    assert excerpt["messages"][-1] == {"role": "ai", "content": "yo"}
    assert excerpt["data"] == {"k": "v"}


# --------------------------------------------------------------------- Field opt-in
def test_secret_input_cannot_enable_expressions() -> None:
    with pytest.raises(ValueError, match="cannot enable expressions"):
        fields.SecretInput(name="secret", expressions=True)
    # the default is fine
    assert fields.SecretInput(name="secret").expressions is False


def test_field_defaults_to_no_expressions() -> None:
    assert fields.StrInput(name="s").expressions is False
    assert fields.StrInput(name="s", expressions=True).expressions is True


# --------------------------------------------------------------- BuildContext wiring
class _ExprProbe(Component):
    component_id = "test.expr_probe"
    display_name = "Expr Probe"
    icon = "box"
    category = "io"

    inputs = [
        fields.StrInput(name="text", display_name="Text", expressions=True),
        fields.StrInput(name="plain", display_name="Plain"),  # opt-out (default)
        fields.HandleField(name="input", display_name="Input", as_port=ports.ANY),
    ]
    outputs = [Output(name="text", display_name="Text", port=ports.TEXT)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {"text": str(ctx.get_input(state, "text") or "")}

        return node


def test_get_input_renders_enabled_field_get_field_returns_raw() -> None:
    node = ComponentTestHarness().build(
        _ExprProbe,
        config={"text": "{{ state.data.k }}", "plain": "{{ state.data.k }}"},
    )
    ctx = node.ctx
    state = {"data": {"k": "hi"}}
    assert ctx.get_input(state, "text") == "hi"  # opted-in → rendered from state
    assert ctx.get_input(state, "plain") == "{{ state.data.k }}"  # opted-out → literal
    assert ctx.get_field("text") == "{{ state.data.k }}"  # compile-time → raw template


def test_expression_reads_bound_input_port() -> None:
    node = ComponentTestHarness().build(
        _ExprProbe, config={"text": "Hi {{ input.name }}"}, ports={"name": "Ada"}
    )
    assert node.ctx.get_input({}, "text") == "Hi Ada"


async def test_probe_node_runs_expression_end_to_end() -> None:
    node = ComponentTestHarness().build(_ExprProbe, config={"text": "{{ state.data.k | upper }}"})
    out = await node({"data": {"k": "hi"}})
    assert out["text"] == "HI"


# ------------------------------------------------------------------ compiler (P3)
def _registry_with(*extra: type[Component]) -> ComponentRegistry:
    registry = ComponentRegistry()
    for cls in get_registry().components.values():
        registry.register(cls, "test")
    for cls in extra:
        registry.register(cls, "test")
    return registry


def _probe_spec(text_value: str) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "flow": {"name": "expr", "slug": "expr", "description": "expr flow"},
        "nodes": [
            {
                "id": "start",
                "component_id": "lab.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "probe",
                "component_id": "test.expr_probe",
                "component_version": "1.0.0",
                "config": {"text": text_value},
                "position": {"x": 100, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lab.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 200, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "probe", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "probe", "output": "text"},
                "target": {"node": "end", "input": "message"},
            },
        ],
    }


def test_bad_expression_emits_e018() -> None:
    compiled = compile_flow(
        _probe_spec("{{ "), registry=_registry_with(_ExprProbe), use_cache=False
    )
    diag = next(d for d in compiled.diagnostics if d.code == DiagnosticCode.E018)
    assert diag.severity == Severity.ERROR
    assert diag.node_id == "probe"
    assert diag.field == "text"
    assert not compiled.ok


def test_unknown_path_emits_w205_warning() -> None:
    compiled = compile_flow(
        _probe_spec("{{ foo.bar }}"), registry=_registry_with(_ExprProbe), use_cache=False
    )
    w205 = [d for d in compiled.diagnostics if d.code == DiagnosticCode.W205]
    assert len(w205) == 1
    assert w205[0].severity == Severity.WARNING
    assert "foo" in w205[0].message


def test_valid_expression_has_no_expression_diagnostics() -> None:
    compiled = compile_flow(
        _probe_spec("{{ state.data.k }}"),
        registry=_registry_with(_ExprProbe),
        use_cache=False,
    )
    codes = {d.code for d in compiled.diagnostics}
    assert DiagnosticCode.E018 not in codes
    assert DiagnosticCode.W205 not in codes


# ------------------------------------------------------------------ coercion (W203)
def test_string_to_number_coercion_inserts_w203() -> None:
    numeric = PortSpec(
        schema_ref="lab:Count", json_schema={"type": "number"}, family=PortFamily.DATA
    )
    compat = check_compatibility(TEXT, numeric)
    assert compat.compatible
    assert compat.warning == "W203"
    assert compat.coercion == "string_to_number"


def test_string_to_number_integer_target_also_coerces() -> None:
    integer = PortSpec(
        schema_ref="lab:Age", json_schema={"type": "integer"}, family=PortFamily.DATA
    )
    assert check_compatibility(TEXT, integer).coercion == "string_to_number"


def test_string_to_number_apply() -> None:
    assert coerce.apply("string_to_number", "42") == 42
    assert coerce.apply("string_to_number", "3.14") == 3.14
    assert coerce.apply("string_to_number", "not-a-number") == "not-a-number"
