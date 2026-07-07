"""Plain-text IO variants + webhook input (SPEC §12.1)."""

from __future__ import annotations

from typing import Any

from lga.sdk import Component, NodeKind, Output, fields, ports
from lga.sdk.templating import last_message_text


class TextInput(Component):
    component_id = "lga.io.text_input"
    display_name = "Text Input"
    description = "A literal or run-supplied text value."
    icon = "type"
    category = "io"

    inputs = [
        fields.MultilineInput(name="value", display_name="Value", tool_mode=True),
        fields.BoolInput(
            name="from_message",
            display_name="Use Inbound Message",
            info="When on, emits the inbound chat message text instead of the literal.",
            default=False,
        ),
        # pure trigger port so literals can be chained behind `start`
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [Output(name="text", display_name="Text", port=ports.TEXT)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            if ctx.get_field("from_message"):
                return {"text": last_message_text(state, human_only=True)}
            return {"text": str(ctx.get_field("value") or "")}

        return node


class TextOutput(Component):
    component_id = "lga.io.text_output"
    display_name = "Text Output"
    description = "Terminal node emitting plain text."
    icon = "align-left"
    category = "io"
    node_kind = NodeKind.TERMINAL

    inputs = [fields.HandleField(name="text", display_name="Text", as_port=ports.TEXT)]
    outputs = [Output(name="result", display_name="Result", port=ports.TEXT)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {"result": str(ctx.get_input(state, "text") or "")}

        return node


class WebhookInput(Component):
    component_id = "lga.io.webhook_input"
    display_name = "Webhook Input"
    description = "Exposes data.webhook_payload, optionally typed via a JSON schema."
    icon = "webhook"
    category = "io"

    inputs = [
        fields.NestedDictInput(
            name="payload_schema",
            display_name="Payload Schema",
            info="Optional JSON Schema describing the webhook body.",
            advanced=True,
        ),
        # trigger port: webhook flows still start at `start`
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [Output(name="payload", display_name="Payload", port=ports.JSON)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            payload = (state.get("data") or {}).get("webhook_payload") or {}
            return {"payload": payload}

        return node
