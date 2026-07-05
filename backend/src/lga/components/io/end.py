"""Chat Output — the reserved `end` node; TERMINAL (SPEC §12.1)."""

from __future__ import annotations

from typing import Any

from lga.sdk import Component, NodeKind, Output, fields, ports
from lga.sdk.templating import message_text


class End(Component):
    component_id = "lga.io.end"
    display_name = "End"
    description = "Flow exit: formats the final artifact from message/text/json input."
    icon = "flag"
    category = "io"
    node_kind = NodeKind.TERMINAL

    inputs = [
        fields.HandleField(name="message", display_name="Message", as_port=ports.MESSAGE),
        fields.HandleField(name="text", display_name="Text", as_port=ports.TEXT),
        fields.HandleField(name="json", display_name="Json", as_port=ports.JSON),
    ]
    outputs = [Output(name="result", display_name="Result", port=ports.ANY)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            message = ctx.get_input(state, "message")
            text = ctx.get_input(state, "text")
            json_value = ctx.get_input(state, "json")
            result: Any
            if message is not None:
                result = message
            elif text is not None:
                result = str(text)
            elif json_value is not None:
                result = json_value
            else:
                # fall back to the last assistant message of the conversation
                msgs = [m for m in state.get("messages") or [] if getattr(m, "type", "") == "ai"]
                result = ports.Message(role="assistant", content=message_text(msgs[-1])) if msgs else ""
            return {"result": result}

        return node
