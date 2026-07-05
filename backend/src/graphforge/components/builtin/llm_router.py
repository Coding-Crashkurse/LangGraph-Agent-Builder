"""LLM classification router: one labeled output per configured label."""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from graphforge.components.base import BuildContext, ComponentConfig, NodeFn, RouterComponent
from graphforge.components.registry import register
from graphforge.components.templating import last_message_text, message_text
from graphforge.runtime.events import emit


class LLMRouterConfig(ComponentConfig):
    model: str = Field("openai:gpt-4o-mini", description="init_chat_model string.")
    labels: list[str] = Field(
        default=["yes", "no"],
        min_length=2,
        description="Branch labels — one source handle per label.",
    )
    instruction: str = Field(
        "",
        description="Classification criteria; the router sees the last message.",
        json_schema_extra={"format": "textarea"},
    )


def _match_label(raw: str, labels: list[str]) -> str:
    cleaned = raw.strip().strip('"').strip("'").lower()
    for label in labels:
        if cleaned == label.lower():
            return label
    for label in labels:
        if label.lower() in cleaned:
            return label
    return labels[0]


@register
class LLMRouter(RouterComponent):
    name = "llm_router"
    display_name = "LLM Router"
    description = "Classifies the conversation into one of the configured labels."
    category = "flow"
    version = 1
    config_model = LLMRouterConfig
    state_reads = ["messages"]
    state_writes = ["route"]
    outputs_from_config = "labels"

    def outputs(self, config: LLMRouterConfig) -> list[str]:
        return list(config.labels)

    def build(self, config: LLMRouterConfig, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], _config: Any) -> dict[str, Any]:
            model = init_chat_model(config.model, temperature=0.0)
            system = (
                "You are a strict classifier. "
                f"{config.instruction}\n"
                f"Answer with exactly one of these labels and nothing else: "
                f"{', '.join(config.labels)}"
            )
            last = last_message_text(state)
            response = await model.ainvoke(
                [SystemMessage(content=system), HumanMessage(content=last or "(empty)")]
            )
            route = _match_label(message_text(response), config.labels)
            emit("router.decision", {"route": route, "raw": message_text(response)[:200]})
            return {"route": route}

        return node
