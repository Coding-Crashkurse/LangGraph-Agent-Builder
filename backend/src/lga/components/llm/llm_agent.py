"""LLM Agent — explicit tool-calling loop (SPEC §12.2).

Deliberately not `create_react_agent`: we control tool-call event emission and
stay robust against prebuilt API drift.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage

from lga.sdk import Component, Output, fields, ports
from lga.sdk.ports import resolve_toolsets
from lga.sdk.runtime import get_run_context
from lga.sdk.templating import message_text


class LLMAgent(Component):
    component_id = "lga.llm.llm_agent"
    display_name = "LLM Agent"
    description = "Chat model with attached tools; loops until no more tool calls."
    icon = "brain"
    category = "llm"

    inputs = [
        fields.ModelInput(name="model", display_name="Model", required=True),
        fields.MultilineInput(
            name="system_prompt",
            display_name="System Prompt",
            default="You are a helpful assistant.",
        ),
        fields.ToolsInput(name="tools", display_name="Tools"),
        fields.IntInput(
            name="max_iterations", display_name="Max Iterations", default=6, min=1, max=25
        ),
        fields.BoolInput(
            name="use_documents",
            display_name="Use Documents",
            info="Inject retrieved documents into the system prompt (RAG).",
            default=False,
            advanced=True,
        ),
        fields.HandleField(name="documents", display_name="Documents", as_port=ports.DOCUMENTS),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [Output(name="message", display_name="Message", port=ports.MESSAGE)]

    def build(self, ctx):
        from lga.components.llm._models import resolve_model
        from lga.runtime.tools import as_langchain_tools

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            tool_defs = await resolve_toolsets(ctx.tools)
            tools = as_langchain_tools(tool_defs)
            model = resolve_model(ctx.get_field("model"))
            if tools:
                try:
                    model = model.bind_tools(tools)
                except NotImplementedError:
                    rc.emit_log("warning", "model does not support tool binding; "
                                           "tools attached but unused")

            system = str(ctx.get_field("system_prompt") or "")
            if ctx.get_field("use_documents"):
                docs = ctx.get_input(state, "documents") or []
                if docs:
                    blocks = []
                    for i, doc in enumerate(docs, start=1):
                        meta = getattr(doc, "metadata", None) or (
                            doc.get("metadata", {}) if isinstance(doc, dict) else {}
                        )
                        source = f" (source: {meta['source']})" if meta.get("source") else ""
                        content = getattr(doc, "page_content", None) or (
                            doc.get("page_content", "") if isinstance(doc, dict) else str(doc)
                        )
                        blocks.append(f"[{i}]{source}\n{content}")
                    system += "\n\n## Context documents\n" + "\n\n".join(blocks)

            conversation: list[BaseMessage] = list(state.get("messages") or [])
            tools_by_name = {t.name: t for t in tools}
            new_messages: list[BaseMessage] = []
            for _ in range(int(ctx.get_field("max_iterations") or 6)):
                rc.raise_if_cancelled()
                response = await model.ainvoke(
                    [SystemMessage(content=system), *conversation, *new_messages]
                )
                new_messages.append(response)
                tool_calls = list(getattr(response, "tool_calls", None) or [])
                if not tool_calls:
                    break
                for call in tool_calls:
                    rc.emit("agent.tool_call", {"tool": call["name"], "args": call.get("args", {})})
                    tool = tools_by_name.get(call["name"])
                    if tool is None:
                        result: Any = f"Unknown tool: {call['name']}"
                    else:
                        try:
                            result = await tool.ainvoke(call.get("args", {}))
                        except Exception as exc:  # tool errors go back to the model
                            result = f"Tool error: {exc}"
                    new_messages.append(
                        ToolMessage(
                            content=result if isinstance(result, str) else str(result),
                            tool_call_id=call.get("id") or call["name"],
                        )
                    )
            final = message_text(new_messages[-1]) if new_messages else ""
            rc.emit("agent.answer", {"preview": final[:300]})
            return {
                "message": ports.Message(role="assistant", content=final),
                "messages": new_messages,
            }

        return node
