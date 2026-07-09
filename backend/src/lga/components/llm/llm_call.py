"""LLM Call â€” one-shot completion with dynamic {var} prompt ports (SPEC Â§12.2)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage

from lga.sdk import Component, Output, fields, ports
from lga.sdk.component import BuildContext, NodeFn
from lga.sdk.runtime import get_run_context
from lga.sdk.templating import PROMPT_VAR_RE, render_prompt


def collect_prompt_values(
    ctx: BuildContext, state: dict[str, Any], template: str
) -> dict[str, Any]:
    """Resolve {var} values: connected port > shared data key > config field."""
    values: dict[str, Any] = {}
    data = state.get("data") or {}
    for var in PROMPT_VAR_RE.findall(template):
        value = ctx.get_input(state, var)
        if value is None:
            value = data.get(var)
        values[var] = value
    return values


class LLMCall(Component):
    component_id = "lga.llm.llm_call"
    display_name = "LLM Call"
    description = "Single completion, no tools. {vars} in the prompt become input ports."
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
        fields.ModelInput(
            name="model", display_name="Model", required=True, as_port=ports.LANGUAGE_MODEL
        ),
        fields.MultilineInput(name="system", display_name="System Prompt", advanced=True),
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
        from lga.components.llm._models import resolve_model

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            template = str(ctx.get_field("prompt") or "")
            prompt = render_prompt(template, collect_prompt_values(ctx, state, template))
            model = resolve_model(ctx.get_input(state, "model"))
            structured = bool(ctx.get_field("structured_output"))
            schema = ctx.get_field("output_schema") or None
            messages: list[Any] = []
            system = ctx.get_field("system")
            if system:
                messages.append(SystemMessage(content=str(system)))
            if structured and schema:
                messages.append(
                    SystemMessage(
                        content="Respond ONLY with JSON matching this schema:\n"
                        + json.dumps(schema)
                    )
                )
            from langchain_core.messages import HumanMessage

            messages.append(HumanMessage(content=prompt))

            text = ""
            if ctx.get_field("stream_tokens"):
                async for chunk in model.astream(messages):
                    delta = chunk.content if isinstance(chunk.content, str) else ""
                    if delta:
                        text += delta
                        rc.stream_writer(delta)
            else:
                response = await model.ainvoke(messages)
                text = (
                    response.content if isinstance(response.content, str) else str(response.content)
                )

            result: dict[str, Any] = {
                "message": ports.Message(role="assistant", content=text),
                "text": text,
                "messages": [AIMessage(content=text)],
            }
            if structured:
                try:
                    result["json"] = json.loads(text)
                except json.JSONDecodeError:
                    result["json"] = {"raw": text}
            return result

        return node
