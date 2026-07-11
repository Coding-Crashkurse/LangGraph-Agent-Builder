"""Plain-text IO variants + webhook input (SPEC §12.1)."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.templating import last_message_text


class TextInput(Component):
    component_id = "lab.io.text_input"
    legacy = True
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
        # pure trigger port so literals can be chained behind ANY upstream node
        fields.HandleField(name="input", display_name="Input", as_port=ports.ANY),
    ]
    outputs = [Output(name="text", display_name="Text", port=ports.TEXT)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            if ctx.get_field("from_message"):
                return {"text": last_message_text(state, human_only=True)}
            return {"text": str(ctx.get_field("value") or "")}

        return node


class TextOutput(Component):
    component_id = "lab.io.text_output"
    legacy = True
    display_name = "Text Output"
    description = "Terminal node emitting plain text."
    icon = "align-left"
    category = "io"
    node_kind = NodeKind.TERMINAL

    inputs = [fields.HandleField(name="text", display_name="Text", as_port=ports.TEXT)]
    outputs = [Output(name="result", display_name="Result", port=ports.TEXT)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {"result": str(ctx.get_input(state, "text") or "")}

        return node


class WebhookInput(Component):
    component_id = "lab.io.webhook_input"
    legacy = True
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
        fields.HandleField(name="input", display_name="Input", as_port=ports.ANY),
    ]
    outputs = [Output(name="payload", display_name="Payload", port=ports.JSON)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            payload = (state.get("data") or {}).get("webhook_payload") or {}
            return {"payload": payload}

        return node
