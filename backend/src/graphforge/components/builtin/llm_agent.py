"""LLM agent with tool-calling loop.

Implemented as an explicit tool loop (not `create_react_agent`) so we control
`agent.tool_call` event emission and stay robust against prebuilt API drift."""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from pydantic import Field

from graphforge.components.base import BaseComponent, BuildContext, ComponentConfig, NodeFn
from graphforge.components.registry import register
from graphforge.components.templating import message_text
from graphforge.runtime.events import emit


class LLMAgentConfig(ComponentConfig):
    model: str = Field(
        "openai:gpt-4o-mini",
        description="init_chat_model string, e.g. 'openai:gpt-4o-mini'.",
    )
    system_prompt: str = Field(
        "You are a helpful assistant.",
        description="System prompt for the agent.",
        json_schema_extra={"format": "textarea"},
    )
    use_documents: bool = Field(
        False, description="Inject state['documents'] into the system prompt (RAG)."
    )
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    max_tool_rounds: int = Field(8, ge=1, le=25, description="Safety cap on tool-call rounds.")


def _render_documents(documents: list[Any]) -> str:
    blocks = []
    for i, doc in enumerate(documents, start=1):
        source = ""
        metadata = getattr(doc, "metadata", None) or {}
        if metadata.get("source"):
            source = f" (source: {metadata['source']})"
        blocks.append(f"[{i}]{source}\n{getattr(doc, 'page_content', str(doc))}")
    return "\n\n".join(blocks)


@register
class LLMAgent(BaseComponent):
    name = "llm_agent"
    display_name = "LLM Agent"
    description = "Chat model with optional attached tools; loops until no more tool calls."
    category = "llm"
    version = 1
    config_model = LLMAgentConfig
    state_reads = ["messages", "documents"]
    state_writes = ["messages"]
    accepts_attachments = ["tools"]

    def build(self, config: LLMAgentConfig, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], _config: Any) -> dict[str, Any]:
            tools = await ctx.get_attached_tools()
            model = init_chat_model(config.model, temperature=config.temperature)
            if tools:
                model = model.bind_tools(tools)
            system = config.system_prompt
            if config.use_documents:
                documents = state.get("documents") or []
                if documents:
                    system += "\n\n## Context documents\n" + _render_documents(documents)

            conversation: list[BaseMessage] = list(state.get("messages") or [])
            tools_by_name = {t.name: t for t in tools}
            new_messages: list[BaseMessage] = []
            for _ in range(config.max_tool_rounds):
                response = await model.ainvoke(
                    [SystemMessage(content=system), *conversation, *new_messages]
                )
                new_messages.append(response)
                tool_calls = list(getattr(response, "tool_calls", None) or [])
                if not tool_calls:
                    break
                for call in tool_calls:
                    emit("agent.tool_call", {"tool": call["name"], "args": call.get("args", {})})
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
            emit(
                "agent.answer",
                {"preview": message_text(new_messages[-1])[:300] if new_messages else ""},
            )
            return {"messages": new_messages}

        return node
