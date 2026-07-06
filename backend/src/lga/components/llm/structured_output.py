"""Structured Output — force Json per schema from a model (SPEC §12.2)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from lga.sdk import Component, Output, fields, ports


class StructuredOutput(Component):
    component_id = "lga.llm.structured_output"
    display_name = "Structured Output"
    description = "Force a model to emit JSON matching a schema."
    icon = "braces"
    category = "llm"

    inputs = [
        fields.ModelInput(name="model", display_name="Model", required=True),
        fields.NestedDictInput(name="output_schema", display_name="Output Schema", required=True),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
        fields.MultilineInput(name="instructions", display_name="Instructions", advanced=True),
    ]
    outputs = [Output(name="json", display_name="Json", port=ports.JSON)]

    def build(self, ctx):
        from lga.components.llm._models import resolve_model
        from lga.sdk.templating import message_text

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            schema = ctx.get_field("output_schema") or {"type": "object"}
            model = resolve_model(ctx.get_field("model"))
            inbound = ctx.get_input(state, "input")
            text = message_text(inbound) if inbound is not None else ""
            response = await model.ainvoke(
                [
                    SystemMessage(
                        content=(ctx.get_field("instructions") or "Extract structured data.")
                        + "\nRespond ONLY with JSON matching this schema:\n"
                        + json.dumps(schema)
                    ),
                    HumanMessage(content=text),
                ]
            )
            raw = response.content if isinstance(response.content, str) else str(response.content)
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = {"raw": raw}
            return {"json": value}

        return node
