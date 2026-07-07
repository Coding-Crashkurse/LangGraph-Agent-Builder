"""Language Model — a shareable model handle (Langflow parity, SPEC §18).

The MODEL port carries the provider *config dict* (not a client instance), so
it serializes cleanly into checkpoints; consumers resolve it lazily.
"""

from __future__ import annotations

from typing import Any

from lga.sdk import Component, Output, fields, ports


class LanguageModel(Component):
    component_id = "lga.llm.language_model"
    display_name = "Language Model"
    description = "Configure a model once, feed it to Call/Agent/Router via the cyan port."
    icon = "cpu"
    category = "llm"
    priority = 2

    inputs = [
        fields.ModelInput(name="model", display_name="Model", required=True),
        fields.SliderInput(
            name="temperature",
            display_name="Temperature",
            min=0.0,
            max=2.0,
            step=0.1,
            default=0.0,
            advanced=True,
        ),
        fields.SecretInput(
            name="api_key",
            display_name="API Key",
            info="Optional override; usually use provider env vars or a stored credential.",
            advanced=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [Output(name="model", display_name="Model", port=ports.LANGUAGE_MODEL)]

    def build(self, ctx):
        from lga.components.llm._models import parse_model_value

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            value = parse_model_value(ctx.get_field("model") or {})
            if ctx.get_field("temperature") is not None:
                value["temperature"] = ctx.get_field("temperature")
            if ctx.get_field("api_key"):
                value["api_key"] = str(ctx.get_field("api_key"))
            return {"model": value}

        return node
