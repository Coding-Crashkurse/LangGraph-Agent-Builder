"""Human-in-the-loop components (SPEC §5.5, §12.3): Approval + Input."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from lga.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from lga.sdk.component import NodeFn
from lga.sdk.interrupts import ApprovalRequest, InputRequest
from lga.sdk.templating import last_message_text


class HumanApproval(Component):
    component_id = "lga.flow.human_approval"
    display_name = "Human Approval"
    description = "Pauses the flow (interrupt) until a human approves or rejects."
    icon = "user-check"
    category = "flow_control"
    node_kind = NodeKind.INTERRUPT

    inputs = [
        fields.MultilineInput(
            name="prompt", display_name="Prompt", default="Approve this step?", required=True
        ),
        fields.BoolInput(
            name="include_preview",
            display_name="Include Message Preview",
            info="Attach the last message to the approval context.",
            default=True,
        ),
        fields.BoolInput(
            name="append_comment",
            display_name="Append Reviewer Comment",
            info="Append the reviewer's comment to the conversation.",
            default=True,
            advanced=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [
        Output(name="approve", display_name="Approve", port=ports.ROUTE),
        Output(name="reject", display_name="Reject", port=ports.ROUTE),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            context: dict[str, Any] = {}
            if ctx.get_field("include_preview"):
                context["preview"] = last_message_text(state)[:500]
            payload = ApprovalRequest(
                prompt=str(ctx.get_field("prompt") or "Approve?"), context=context
            )
            resume = interrupt(payload.model_dump())
            decision = "reject"
            comment = None
            if isinstance(resume, dict):
                decision = str(resume.get("decision", "reject")).lower()
                comment = resume.get("comment")
            elif isinstance(resume, str):
                decision = resume.strip().lower()
            if decision not in ("approve", "reject"):
                decision = "reject"
            result: dict[str, Any] = {"route": decision}
            if comment and ctx.get_field("append_comment"):
                result["messages"] = [HumanMessage(content=f"[reviewer] {comment}")]
            return result

        return node


class HumanInput(Component):
    component_id = "lga.flow.human_input"
    display_name = "Human Input"
    description = "Pauses the flow for free-text (or schema-validated) human input."
    icon = "message-square"
    category = "flow_control"
    node_kind = NodeKind.INTERRUPT

    inputs = [
        fields.MultilineInput(
            name="prompt", display_name="Prompt", default="Please provide input.", required=True
        ),
        fields.NestedDictInput(
            name="input_schema",
            display_name="Input Schema",
            info="Optional JSON Schema for structured input.",
            advanced=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [Output(name="message", display_name="Message", port=ports.MESSAGE)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            schema = ctx.get_field("input_schema") or None
            payload = InputRequest(prompt=str(ctx.get_field("prompt") or ""), schema_=schema)
            resume = interrupt(payload.model_dump(by_alias=True))
            if isinstance(resume, dict) and "text" in resume and schema is None:
                text = str(resume["text"])
            elif isinstance(resume, dict):
                import json

                text = json.dumps(resume, ensure_ascii=False)
            else:
                text = str(resume)
            return {
                "message": ports.Message(role="user", content=text),
                "messages": [HumanMessage(content=text)],
            }

        return node
