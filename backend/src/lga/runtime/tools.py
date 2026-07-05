"""Tool plumbing: ToolDef ⇄ LangChain tools, node-as-tool wrapping (SPEC §4.7)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from lga.sdk.component import BuildContext, InputBinding
from lga.sdk.ports import ToolDef


def as_langchain_tools(defs: list[ToolDef]) -> list[Any]:
    """ToolDefs → LangChain BaseTools (callable_ref may already be one)."""
    from langchain_core.tools import BaseTool, StructuredTool

    tools: list[Any] = []
    for td in defs:
        ref = td.callable_ref
        if isinstance(ref, BaseTool):
            tools.append(ref)
            continue
        if ref is None:
            continue
        schema = td.args_schema or {"type": "object", "properties": {}}
        tools.append(
            StructuredTool.from_function(
                coroutine=ref,
                name=td.name,
                description=td.description,
                args_schema=schema,
            )
        )
    return tools


def node_as_tool(node_ir: Any, ctx: BuildContext) -> ToolDef:
    """Wrap a tool_mode_supported node as a ToolDef (SPEC §4.7).

    Tool arguments override the node's field values for that invocation; the
    node runs on a minimal standalone state and its primary output is returned.
    """
    cls = node_ir.component
    schema_info = cls.tool_schema(node_ir.config, ctx.label)

    async def invoke(**kwargs: Any) -> str:
        call_ctx = replace(
            ctx,
            config={**node_ir.config, **kwargs},
            input_bindings={
                name: InputBinding(input_name=name, channel=None, constant=value)
                for name, value in kwargs.items()
            },
        )
        fn = cls().build(call_ctx)
        state: dict[str, Any] = {"messages": [], "data": dict(kwargs), "ports": {}, "route": {}}
        result = await fn(state, {"configurable": {}}) or {}
        outputs = cls.outputs_for_config(call_ctx.config)
        for out in outputs:
            if out.name in result and out.name != "toolset":
                value = result[out.name]
                return value if isinstance(value, str) else _stringify(value)
        return _stringify(result)

    return ToolDef(
        name=schema_info["name"],
        description=schema_info["description"],
        args_schema=schema_info["args_schema"],
        callable_ref=invoke,
    )


def _stringify(value: Any) -> str:
    import json

    from lga.sdk.ports import Message

    if isinstance(value, Message):
        return value.content
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)
