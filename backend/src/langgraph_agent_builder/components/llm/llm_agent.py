"""LLM Agent — explicit tool-calling loop (SPEC §12.2).

Deliberately not `create_react_agent`: we control tool-call event emission and
stay robust against prebuilt API drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage

from langgraph_agent_builder.sdk import Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import BuildContext, NodeFn
from langgraph_agent_builder.sdk.ports import LazyToolset, ToolDef, resolve_toolsets

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
from langgraph_agent_builder.sdk.runtime import get_run_context
from langgraph_agent_builder.sdk.templating import message_text


class LLMAgent(Component):
    component_id = "lab.llm.llm_agent"
    display_name = "LLM Agent"
    description = "Chat model with attached tools; loops until no more tool calls."
    icon = "brain"
    category = "llm"
    priority = 1

    inputs = [
        fields.ModelInput(
            name="model", display_name="Model", required=True, as_port=ports.LANGUAGE_MODEL
        ),
        fields.PromptInput(
            name="system_prompt",
            display_name="System Prompt",
            info="{variables} spawn input ports and resolve from ports or data.",
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

    def build(self, ctx: BuildContext) -> NodeFn:
        from langgraph_agent_builder.components.llm._models import resolve_model
        from langgraph_agent_builder.components.llm.llm_call import collect_prompt_values
        from langgraph_agent_builder.runtime.tools import as_langchain_tools
        from langgraph_agent_builder.sdk.templating import render_prompt

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            tool_defs = await resolve_toolsets(cast(list[ToolDef | LazyToolset], ctx.tools))
            tools = as_langchain_tools(tool_defs)
            model = resolve_model(ctx.get_input(state, "model"))
            if tools:
                try:
                    model = cast("BaseChatModel", model.bind_tools(tools))
                except NotImplementedError:
                    rc.emit_log(
                        "warning", "model does not support tool binding; tools attached but unused"
                    )

            template = str(ctx.get_field("system_prompt") or "")
            system = render_prompt(template, collect_prompt_values(ctx, state, template))
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
                    import time as _time

                    rc.emit(
                        "tool_call",
                        {"tool_name": call["name"], "args_preview": call.get("args", {})},
                    )
                    _t0 = _time.perf_counter()
                    tool = tools_by_name.get(call["name"])
                    if tool is None:
                        result: Any = f"Unknown tool: {call['name']}"
                    else:
                        try:
                            result = await tool.ainvoke(call.get("args", {}))
                        except Exception as exc:  # tool errors go back to the model
                            result = f"Tool error: {exc}"
                    rc.emit(
                        "tool_result",
                        {
                            "tool_name": call["name"],
                            "result_preview": (result if isinstance(result, str) else str(result))[
                                :300
                            ],
                            "duration_ms": round((_time.perf_counter() - _t0) * 1000, 2),
                        },
                    )
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
