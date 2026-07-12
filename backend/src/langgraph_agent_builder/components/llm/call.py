"""LLM Call — one-shot completion over a model-provider resource (palette v2).

The successor of :class:`~langgraph_agent_builder.components.llm.llm_call.LLMCall`:
identical completion behavior, but the model is a **Resource** reference
(``model_provider``) instead of an inline ModelInput, and it absorbs the old
Structured Output node via the ``structured_output``/``output_schema`` fields.
{vars} in the prompt still spawn dynamic input ports.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from langgraph_agent_builder.sdk import Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import BuildContext, NodeFn
from langgraph_agent_builder.sdk.runtime import get_run_context
from langgraph_agent_builder.sdk.templating import render_prompt


class Call(Component):
    component_id = "lab.llm.call"
    display_name = "LLM Call"
    description = (
        "Single completion over a model provider resource, no tools. "
        "{vars} in the prompt become input ports; can force structured JSON output."
    )
    icon = "sparkles"
    category = "llm"
    tool_mode_supported = True
    priority = 0

    inputs = [
        fields.PromptInput(
            name="prompt",
            display_name="Prompt",
            required=True,
            tool_mode=True,
            info="{variables} spawn input ports and resolve from ports or data.",
        ),
        fields.ResourceRefInput(
            name="model",
            display_name="Model",
            resource_type="model_provider",
            required=True,
            info="A model provider resource; pick the model on the reference.",
        ),
        fields.MultilineInput(
            name="system",
            display_name="System Prompt",
            advanced=True,
            expressions=True,
            info="Supports {{ … }} expressions over {input, state, vars}.",
        ),
        fields.BoolInput(
            name="structured_output",
            display_name="Structured Output",
            info="Force JSON output matching `output_schema`.",
            default=False,
            advanced=True,
        ),
        fields.NestedDictInput(name="output_schema", display_name="Output Schema", advanced=True),
        fields.BoolInput(
            name="stream_tokens", display_name="Stream Tokens", default=True, advanced=True
        ),
    ]
    outputs = [
        Output(name="message", display_name="Message", port=ports.MESSAGE),
        Output(name="text", display_name="Text", port=ports.TEXT),
        Output(name="json", display_name="Json", port=ports.JSON),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        from langgraph_agent_builder.components.llm._models import (
            parse_json_reply,
            resolve_model_resource,
            stream_completion,
        )
        from langgraph_agent_builder.components.llm.llm_call import collect_prompt_values

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            template = str(ctx.get_field("prompt") or "")
            prompt = render_prompt(template, collect_prompt_values(ctx, state, template))
            model = await resolve_model_resource(ctx.get_field("model"))
            structured = bool(ctx.get_field("structured_output"))
            schema = ctx.get_field("output_schema") or None
            messages: list[Any] = []
            system = ctx.get_input(state, "system")
            if system:
                messages.append(SystemMessage(content=str(system)))
            if structured and schema:
                messages.append(
                    SystemMessage(
                        content="Respond ONLY with JSON matching this schema:\n"
                        + json.dumps(schema)
                    )
                )
            messages.append(HumanMessage(content=prompt))

            text = await stream_completion(
                model, messages, rc, bool(ctx.get_field("stream_tokens"))
            )

            result: dict[str, Any] = {
                "message": ports.Message(role="assistant", content=text),
                "text": text,
                "messages": [AIMessage(content=text)],
            }
            if structured:
                result["json"] = parse_json_reply(text)
            return result

        return node
