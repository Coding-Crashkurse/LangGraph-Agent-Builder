"""Unit tests for the IO components (SPEC §12.1).

Covers langgraph_agent_builder.components.io.start, .end and .set_data by driving
each NodeFn directly through the ComponentTestHarness. The emphasis is on the
input precedence branches (End), the jinja rendering + blank-key skipping
(SetData) and the structured-input shaping (Start).
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from langgraph_agent_builder.components.io.end import End
from langgraph_agent_builder.components.io.set_data import SetData
from langgraph_agent_builder.components.io.start import Start
from langgraph_agent_builder.sdk import Component, ports
from langgraph_agent_builder.sdk.testing import BuiltNode, ComponentTestHarness


def _build(
    component: type[Component],
    config: dict[str, Any] | None = None,
    port_values: dict[str, Any] | None = None,
) -> BuiltNode:
    return ComponentTestHarness().build(component, config=config, ports=port_values)


# ----------------------------------------------------------------------- Start
async def test_start_uses_run_meta_input_text() -> None:
    node = _build(Start)
    result = await node({"run_meta": {"input_text": "hello there"}})
    message = result["message"]
    assert isinstance(message, ports.Message)
    assert message.role == "user"
    assert message.content == "hello there"
    assert result["data"] == {}
    assert result["files"] == []


async def test_start_prefers_a2a_input_dict() -> None:
    node = _build(Start)
    result = await node({"run_meta": {"input_text": "x"}, "data": {"a2a_input": {"k": "v"}}})
    assert result["data"] == {"k": "v"}


async def test_start_wraps_non_dict_structured_input() -> None:
    node = _build(Start)
    result = await node({"run_meta": {"input_text": "x", "inputs": "scalar"}})
    assert result["data"] == {"value": "scalar"}


async def test_start_falls_back_to_last_human_message() -> None:
    node = _build(Start)
    result = await node({"messages": [HumanMessage(content="hey")]})
    message = result["message"]
    assert isinstance(message, ports.Message)
    assert message.content == "hey"


async def test_start_passes_through_files() -> None:
    node = _build(Start)
    result = await node({"run_meta": {"input_text": "x", "files": [{"id": "f1"}]}})
    assert result["files"] == [{"id": "f1"}]


# ------------------------------------------------------------------------- End
async def test_end_returns_wired_result() -> None:
    node = _build(End, port_values={"result": ports.Message(role="assistant", content="M")})
    result = await node()
    assert isinstance(result["result"], ports.Message)
    assert result["result"].content == "M"


async def test_end_result_accepts_any_type() -> None:
    node = _build(End, port_values={"result": {"a": 1}})
    result = await node()
    assert result["result"] == {"a": 1}


async def test_end_falls_back_to_last_ai_message() -> None:
    node = _build(End)
    result = await node({"messages": [HumanMessage(content="h"), AIMessage(content="final ai")]})
    assert isinstance(result["result"], ports.Message)
    assert result["result"].content == "final ai"


async def test_end_is_empty_string_without_any_input() -> None:
    node = _build(End)
    result = await node()
    assert result["result"] == ""


# --------------------------------------------------------------------- SetData
async def test_set_data_renders_expression_over_message() -> None:
    node = _build(
        SetData,
        config={
            "entries": [{"key": "greeting", "template": "Hi {{ state.messages[-1].content }}"}]
        },
    )
    result = await node({"messages": [HumanMessage(content="world")]})
    assert result["data"] == {"greeting": "Hi world"}


async def test_set_data_reads_data_variable_and_keeps_typed_value() -> None:
    node = _build(
        SetData,
        config={
            "entries": [
                {"key": "x", "template": "{{ state.data.foo }}"},
                # a whole-cell expression keeps its typed value (the type_convert
                # replacement): count stays an int, not "3"
                {"key": "n", "template": "{{ state.data.count }}"},
            ]
        },
    )
    result = await node({"data": {"foo": "bar", "count": 3}})
    assert result["data"] == {"x": "bar", "n": 3}


async def test_set_data_skips_blank_keys() -> None:
    node = _build(
        SetData,
        config={
            "entries": [
                {"key": "", "template": "ignored"},
                {"key": "  ", "template": "also ignored"},
                {"key": "kept", "template": "yes"},
            ]
        },
    )
    result = await node()
    assert result["data"] == {"kept": "yes"}
