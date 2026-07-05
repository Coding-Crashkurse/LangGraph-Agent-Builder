"""Chat Input — the reserved `start` node (SPEC §12.1)."""

from __future__ import annotations

from typing import Any

from lga.sdk import Component, Output, fields, ports
from lga.sdk.templating import last_message_text


class Start(Component):
    component_id = "lga.io.start"
    display_name = "Start"
    description = "Flow entry: exposes the inbound chat message and structured input."
    icon = "play"
    category = "io"

    inputs = [
        fields.NestedDictInput(
            name="input_schema",
            display_name="Structured Input Schema",
            info="Optional JSON Schema for structured input; feeds the A2A/MCP input contract.",
            advanced=True,
        ),
    ]
    outputs = [
        Output(name="message", display_name="Message", port=ports.MESSAGE),
        Output(name="data", display_name="Data", port=ports.JSON),
        Output(name="files", display_name="Files", port=ports.FILE_REF),
    ]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            run_meta = state.get("run_meta") or {}
            text = run_meta.get("input_text") or last_message_text(state, human_only=True)
            data = dict(state.get("data") or {})
            structured = data.get("a2a_input") or run_meta.get("inputs") or {}
            return {
                "message": ports.Message(role="user", content=text),
                "data": structured if isinstance(structured, dict) else {"value": structured},
                "files": run_meta.get("files") or [],
            }

        return node
