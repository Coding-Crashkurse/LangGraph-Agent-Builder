"""Data components (SPEC §12.6): Prompt Template."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import BuildContext, NodeFn
from langgraph_agent_builder.sdk.ports import Message
from langgraph_agent_builder.sdk.templating import render_prompt


class PromptTemplate(Component):
    component_id = "lab.data.prompt_template"
    display_name = "Prompt"
    description = (
        "Compose a prompt from a template — each {variable} becomes an input port "
        "(wire Documents, Text or values in; Documents coerce to text). Outputs the "
        "rendered Text/Message to feed an LLM Agent's input or an LLM Call {var}."
    )
    icon = "file-text"
    category = "io"
    priority = 30

    inputs = [
        fields.PromptInput(name="template", display_name="Template", required=True),
    ]
    outputs = [
        Output(name="text", display_name="Text", port=ports.TEXT),
        Output(name="message", display_name="Message", port=ports.MESSAGE),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        from langgraph_agent_builder.components.llm._models import collect_prompt_values

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            template = str(ctx.get_field("template") or "")
            text = render_prompt(template, collect_prompt_values(ctx, state, template))
            return {"text": text, "message": Message(role="user", content=text)}

        return node
