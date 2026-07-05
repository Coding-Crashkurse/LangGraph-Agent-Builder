import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from graphforge.compiler.build import FlowValidationError, build_flow
from graphforge.compiler.spec import FlowSpec
from graphforge.components.templating import render_template

from .conftest import simple_flow


async def test_build_and_run_set_data_flow(loaded_registry, settings):
    spec = FlowSpec(
        slug="glue",
        name="Glue",
        nodes=[
            {
                "id": "set",
                "component": "set_data",
                "config": {"values": {"greeting": "hi", "echo": "{last_message}"}},
            }
        ],
        edges=[
            {"source": "__start__", "target": "set"},
            {"source": "set", "target": "__end__"},
        ],
    )
    compiled = build_flow(spec, loaded_registry, settings, InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    result = await compiled.graph.ainvoke(
        {"messages": [HumanMessage(content="hello there")]}, config
    )
    assert result["data"]["greeting"] == "hi"
    assert result["data"]["echo"] == "hello there"


async def test_build_runs_fake_llm(loaded_registry, settings):
    compiled = build_flow(simple_flow(), loaded_registry, settings, InMemorySaver())
    result = await compiled.graph.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        {"configurable": {"thread_id": "t"}},
    )
    assert result["messages"][-1].content == "hello from fake"


def test_build_rejects_invalid_spec(loaded_registry, settings):
    spec = FlowSpec(
        slug="bad",
        name="Bad",
        nodes=[{"id": "a", "component": "nope"}],
        edges=[{"source": "__start__", "target": "a"}],
    )
    with pytest.raises(FlowValidationError) as excinfo:
        build_flow(spec, loaded_registry, settings, InMemorySaver())
    assert any(i.code == "unknown_component" for i in excinfo.value.issues)


def test_render_template_paths():
    state = {
        "messages": [HumanMessage(content="question?")],
        "data": {"query": "42", "nested": {"x": 1}},
        "route": "approved",
    }
    assert render_template("q={last_message} r={route}", state) == "q=question? r=approved"
    assert render_template("{data.query}", state) == "42"
    assert render_template("{data.nested}", state) == '{"x": 1}'
    with pytest.raises(ValueError, match="unknown state path"):
        render_template("{data.missing}", state)
