"""Chat Output — the reserved `end` node; TERMINAL (SPEC §12.1)."""

from __future__ import annotations

from typing import Any

from lga.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from lga.sdk.component import NodeFn
from lga.sdk.templating import message_text


class End(Component):
    component_id = "lga.io.end"
    display_name = "Chat Output"
    description = "Flow exit: formats the final artifact from message/text/json/table input."
    icon = "message-square-reply"
    category = "io"
    node_kind = NodeKind.TERMINAL
    priority = 1

    inputs = [
        fields.HandleField(name="message", display_name="Message", as_port=ports.MESSAGE),
        fields.HandleField(name="text", display_name="Text", as_port=ports.TEXT),
        fields.HandleField(name="json", display_name="Json", as_port=ports.JSON),
        fields.HandleField(name="table", display_name="Table", as_port=ports.TABLE),
    ]
    outputs = [Output(name="result", display_name="Result", port=ports.ANY)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            message = ctx.get_input(state, "message")
            text = ctx.get_input(state, "text")
            json_value = ctx.get_input(state, "json")
            table = ctx.get_input(state, "table")
            result: Any
            if message is not None:
                result = message
            elif text is not None:
                result = str(text)
            elif json_value is not None:
                result = json_value
            elif table is not None:
                result = table
            else:
                # fall back to the last assistant message of the conversation
                msgs = [m for m in state.get("messages") or [] if getattr(m, "type", "") == "ai"]
                result = (
                    ports.Message(role="assistant", content=message_text(msgs[-1])) if msgs else ""
                )
            return {"result": result}

        return node
