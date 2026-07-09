"""Echo LLM — returns its input verbatim (SPEC §1.5-6 testing components)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from lga.sdk import BuildContext, Component, Output, fields, ports
from lga.sdk.component import NodeFn
from lga.sdk.templating import last_message_text, message_text


class EchoLLM(Component):
    component_id = "lga.testing.echo_llm"
    display_name = "Echo LLM (testing)"
    description = "Echoes the incoming message back. Zero-dependency pipeline testing."
    icon = "repeat-2"
    category = "testing"
    tool_mode_supported = True

    inputs = [
        fields.StrInput(
            name="prefix",
            display_name="Prefix",
            info="Optional prefix prepended to the echoed text.",
            default="",
            tool_mode=True,
        ),
        fields.BoolInput(
            name="uppercase",
            display_name="Uppercase",
            default=False,
            advanced=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [
        Output(name="message", display_name="Message", port=ports.MESSAGE),
        Output(name="text", display_name="Text", port=ports.TEXT),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            inbound = ctx.get_input(state, "input")
            text = message_text(inbound) if inbound is not None else ""
            if not text:
                text = last_message_text(state, human_only=True) or last_message_text(state)
            if ctx.get_field("uppercase"):
                text = text.upper()
            echoed = f"{ctx.get_field('prefix') or ''}{text}"
            return {
                "message": ports.Message(role="assistant", content=echoed),
                "text": echoed,
                "messages": [AIMessage(content=echoed)],
            }

        return node
