"""Unit tests for langgraph_agent_builder.runtime.tools (ToolDef ⇄ LangChain, node-as-tool §4.7)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langgraph_agent_builder.runtime.tools import _stringify, as_langchain_tools, node_as_tool
from langgraph_agent_builder.sdk import fields, ports
from langgraph_agent_builder.sdk.component import BuildContext, Component
from langgraph_agent_builder.sdk.outputs import Output
from langgraph_agent_builder.sdk.ports import Message, ToolDef

# --------------------------------------------------------------------------- helpers


async def _echo(x: str) -> str:
    return x.upper()


async def _noargs() -> str:
    return "ok"


class _JsonTool(Component):
    """Tool-mode component whose primary output is a non-string (JSON)."""

    component_id = "test.jsontool"
    display_name = "JsonTool"
    tool_mode_supported = True
    tool_mode_default = True
    inputs = [fields.StrInput(name="q", tool_mode=True, required=True)]
    outputs = [Output(name="data", port=ports.JSON)]

    def build(self, ctx: BuildContext) -> Any:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {"data": {"q": ctx.get_input(state, "q")}}

        return node


class _EmptyTool(Component):
    """Tool-mode component whose build produces no matching output key."""

    component_id = "test.emptytool"
    display_name = "EmptyTool"
    tool_mode_supported = True
    tool_mode_default = True
    inputs = [fields.StrInput(name="q", tool_mode=True, required=True)]
    outputs = [Output(name="data", port=ports.JSON)]

    def build(self, ctx: BuildContext) -> Any:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node


# --------------------------------------------------------------------------- as_langchain_tools


async def test_as_langchain_tools_wraps_coroutine() -> None:
    td = ToolDef(
        name="echo",
        description="echoes upper",
        args_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        callable_ref=_echo,
    )
    tools = as_langchain_tools([td])
    assert len(tools) == 1
    assert tools[0].name == "echo"
    assert tools[0].description == "echoes upper"
    assert await tools[0].ainvoke({"x": "hi"}) == "HI"


async def test_as_langchain_tools_default_schema_when_empty() -> None:
    td = ToolDef(name="noargs", callable_ref=_noargs)  # args_schema defaults to {}
    tools = as_langchain_tools([td])
    assert tools[0].name == "noargs"
    assert await tools[0].ainvoke({}) == "ok"


async def test_as_langchain_tools_passes_through_basetool() -> None:
    from langchain_core.tools import StructuredTool

    base = StructuredTool.from_function(
        coroutine=_echo,
        name="prebuilt",
        description="d",
        args_schema={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    td = ToolDef(name="ignored-name", callable_ref=base)
    tools = as_langchain_tools([td])
    assert tools[0] is base  # returned unchanged, not re-wrapped


async def test_as_langchain_tools_skips_none_ref() -> None:
    td = ToolDef(name="empty", callable_ref=None)
    assert as_langchain_tools([td]) == []


# --------------------------------------------------------------------------- node_as_tool


async def test_node_as_tool_stringifies_non_string_output() -> None:
    node_ir = SimpleNamespace(component=_JsonTool, config={})
    ctx = BuildContext(node_id="jt", label="JsonTool")
    td = node_as_tool(node_ir, ctx)
    assert td.name == "jsontool"  # slugify(label)
    assert td.args_schema["properties"]["q"]["type"] == "string"
    assert td.args_schema["required"] == ["q"]
    result = await td.callable_ref(q="hello")
    assert result == '{"q": "hello"}'


async def test_node_as_tool_falls_back_to_stringified_result() -> None:
    node_ir = SimpleNamespace(component=_EmptyTool, config={})
    ctx = BuildContext(node_id="et", label="EmptyTool")
    td = node_as_tool(node_ir, ctx)
    # no matching output key → whole (empty) result is stringified
    assert await td.callable_ref(q="x") == "{}"


async def test_node_as_tool_uses_config_tool_name_and_description() -> None:
    node_ir = SimpleNamespace(
        component=_JsonTool,
        config={"tool_name": "lookup", "tool_description": "look things up"},
    )
    ctx = BuildContext(node_id="jt", label="JsonTool")
    td = node_as_tool(node_ir, ctx)
    assert td.name == "lookup"
    assert td.description == "look things up"


# --------------------------------------------------------------------------- _stringify


def test_stringify_message_returns_content() -> None:
    assert _stringify(Message(role="assistant", content="hi there")) == "hi there"


def test_stringify_dict_json_encodes() -> None:
    assert _stringify({"a": 1, "b": "x"}) == '{"a": 1, "b": "x"}'


def test_stringify_typeerror_falls_back_to_str() -> None:
    # non-str dict keys make json.dumps raise TypeError (default= only maps values)
    value = {(1, 2): "tuplekey"}
    out = _stringify(value)
    assert out == str(value)
