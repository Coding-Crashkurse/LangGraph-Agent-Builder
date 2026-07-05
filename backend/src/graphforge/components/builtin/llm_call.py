"""Single LLM completion, no tools."""

import re
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field, field_validator

from graphforge.components.base import BaseComponent, BuildContext, ComponentConfig, NodeFn
from graphforge.components.registry import register
from graphforge.components.templating import message_text, render_template

_OUTPUT_KEY = re.compile(r"^(messages|data\.[a-zA-Z0-9_]+)$")


class LLMCallConfig(ComponentConfig):
    model: str = Field("openai:gpt-4o-mini", description="init_chat_model string.")
    prompt_template: str = Field(
        "{last_message}",
        description=(
            "Jinja-lite over state keys: {last_message}, {last_human_message}, {data.key}, {route}."
        ),
        json_schema_extra={"format": "textarea"},
    )
    system_prompt: str = Field("", json_schema_extra={"format": "textarea"})
    output_key: str = Field(
        "messages", description="Where to write the completion: 'messages' or 'data.<key>'."
    )
    temperature: float = Field(0.0, ge=0.0, le=2.0)

    @field_validator("output_key")
    @classmethod
    def _check_output_key(cls, value: str) -> str:
        if not _OUTPUT_KEY.match(value):
            raise ValueError("output_key must be 'messages' or 'data.<key>'")
        return value


@register
class LLMCall(BaseComponent):
    name = "llm_call"
    display_name = "LLM Call"
    description = "One-shot completion over a prompt template; writes messages or data.<key>."
    category = "llm"
    version = 1
    config_model = LLMCallConfig
    state_reads = ["messages", "data", "route"]
    state_writes = ["messages", "data"]

    def build(self, config: LLMCallConfig, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], _config: Any) -> dict[str, Any]:
            prompt = render_template(config.prompt_template, state)
            model = init_chat_model(config.model, temperature=config.temperature)
            messages = []
            if config.system_prompt:
                messages.append(SystemMessage(content=config.system_prompt))
            messages.append(HumanMessage(content=prompt))
            response = await model.ainvoke(messages)
            if config.output_key == "messages":
                return {"messages": [response]}
            key = config.output_key.removeprefix("data.")
            return {"data": {key: message_text(response)}}

        return node
