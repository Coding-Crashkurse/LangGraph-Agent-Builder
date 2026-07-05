"""Human-in-the-loop components: approval router + free-text input.

Both call langgraph's `interrupt()`; the A2A executor maps that to
`TaskState.input_required` and resumes with `Command(resume=<user input>)`."""

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt
from pydantic import Field

from graphforge.components.base import (
    BaseComponent,
    BuildContext,
    ComponentConfig,
    NodeFn,
    RouterComponent,
)
from graphforge.components.registry import register
from graphforge.components.templating import last_message_text

_APPROVE_WORDS = {"approve", "approved", "accept", "accepted", "yes", "y", "ok", "true", "ja"}


def normalize_decision(value: Any) -> tuple[bool, str]:
    """Map a resume payload (dict from the debug UI, plain text from A2A clients,
    bool) to (approved, comment)."""
    if isinstance(value, dict):
        comment = str(value.get("comment") or value.get("text") or "")
        if "approved" in value:
            return bool(value["approved"]), comment
        if "approve" in value:
            return bool(value["approve"]), comment
        return normalize_decision(comment)[0], comment
    if isinstance(value, bool):
        return value, ""
    text = str(value).strip()
    return text.lower() in _APPROVE_WORDS, text


class HumanApprovalConfig(ComponentConfig):
    prompt: str = Field("Approve this result?", description="Question shown to the reviewer.")
    append_feedback: bool = Field(
        True, description="Append the reviewer comment to messages on rejection."
    )


@register
class HumanApproval(RouterComponent):
    name = "human_approval"
    display_name = "Human Approval"
    description = "Pauses the task (input-required) until a reviewer approves or rejects."
    category = "flow"
    version = 1
    config_model = HumanApprovalConfig
    state_reads = ["messages"]
    state_writes = ["route", "messages"]
    outputs_static = ["approved", "rejected"]

    def outputs(self, config: HumanApprovalConfig) -> list[str]:
        return ["approved", "rejected"]

    def build(self, config: HumanApprovalConfig, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], _config: Any) -> dict[str, Any]:
            decision = interrupt(
                {
                    "kind": "approval",
                    "prompt": config.prompt,
                    "preview": last_message_text(state)[:2000],
                    "node": ctx.node_id,
                }
            )
            approved, comment = normalize_decision(decision)
            update: dict[str, Any] = {"route": "approved" if approved else "rejected"}
            if comment and config.append_feedback and not approved:
                update["messages"] = [HumanMessage(content=f"[reviewer] {comment}")]
            return update

        return node


class HumanInputConfig(ComponentConfig):
    prompt: str = Field("Please provide input.", description="Prompt shown to the human.")


@register
class HumanInput(BaseComponent):
    name = "human_input"
    display_name = "Human Input"
    description = "Pauses for free-text input; the reply is appended as a HumanMessage."
    category = "flow"
    version = 1
    config_model = HumanInputConfig
    state_reads = []
    state_writes = ["messages"]

    def build(self, config: HumanInputConfig, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], _config: Any) -> dict[str, Any]:
            value = interrupt({"kind": "input", "prompt": config.prompt, "node": ctx.node_id})
            if isinstance(value, dict):
                text = str(value.get("text") or value.get("comment") or value)
            else:
                text = str(value)
            return {"messages": [HumanMessage(content=text)]}

        return node
