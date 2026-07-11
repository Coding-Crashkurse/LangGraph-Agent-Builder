"""Fake LLM — scripted replies; the zero-dependency CI backbone (SPEC §12.2)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from langgraph_agent_builder.sdk import BuildContext, Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.runtime import get_run_context


class FakeLLM(Component):
    component_id = "lab.testing.fake_llm"
    display_name = "Fake LLM (testing)"
    description = "Deterministic scripted replies; cycles through `replies`. No API keys."
    icon = "bot"
    category = "testing"
    tool_mode_supported = True

    inputs = [
        fields.NestedDictInput(
            name="replies",
            display_name="Replies",
            info="List of scripted replies; cycled per assistant turn.",
            schema_={"type": "array", "items": {"type": "string"}, "minItems": 1},
            default=["ok"],
            required=True,
            tool_mode=True,
        ),
        fields.BoolInput(
            name="stream_tokens",
            display_name="Stream Tokens",
            info="Emit the reply in 3 token chunks (exercises token streaming).",
            default=False,
            advanced=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [Output(name="message", display_name="Message", port=ports.MESSAGE)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            replies = list(ctx.get_field("replies") or ["ok"])
            ai_count = sum(1 for m in state.get("messages") or [] if getattr(m, "type", "") == "ai")
            reply = str(replies[ai_count % len(replies)])
            rc.emit("fake.thinking", {"reply_index": ai_count % len(replies)})
            if ctx.get_field("stream_tokens"):
                third = max(1, len(reply) // 3)
                for chunk in (reply[:third], reply[third : 2 * third], reply[2 * third :]):
                    if chunk:
                        rc.stream_writer(chunk)
            return {
                "message": ports.Message(role="assistant", content=reply),
                "messages": [AIMessage(content=reply)],
            }

        return node
