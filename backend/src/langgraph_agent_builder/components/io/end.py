"""Chat Output — the reserved `end` node; TERMINAL (SPEC §12.1)."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.templating import message_text


class End(Component):
    component_id = "lab.io.end"
    display_name = "Chat Output"
    description = "Flow exit: the final result — any type (message/text/json/table) coerces here."
    icon = "message-square-reply"
    category = "io"
    node_kind = NodeKind.TERMINAL
    priority = 1

    inputs = [
        # A single ANY input — the four old typed ports (message/text/json/table)
        # were redundant since anything coerces to the flow's final artifact.
        fields.HandleField(name="result", display_name="Result", as_port=ports.ANY),
        fields.NestedDictInput(
            name="output_schema",
            display_name="Structured Output Schema",
            info=(
                "Optional JSON Schema for the flow's structured result. Single source for "
                "the MCP outputSchema/structuredContent, A2A DataPart validation, and the "
                "API response contract (SPEC §5.1)."
            ),
            advanced=True,
        ),
    ]
    # No downstream edges, but the terminal still publishes its resolved value on
    # the `result` channel so the executor's extract_result can read it (SPEC §7.8).
    outputs = [Output(name="result", display_name="Result", port=ports.ANY)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            result = ctx.get_input(state, "result")
            if result is None:
                # fall back to the last assistant message of the conversation
                msgs = [m for m in state.get("messages") or [] if getattr(m, "type", "") == "ai"]
                result = (
                    ports.Message(role="assistant", content=message_text(msgs[-1])) if msgs else ""
                )
            return {"result": result}

        return node
