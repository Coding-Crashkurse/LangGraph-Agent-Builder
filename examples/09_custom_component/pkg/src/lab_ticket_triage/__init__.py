"""Custom component package (SPEC §13/09): a `TicketBatch` port schema proving
structural typing — TicketBatch edges only connect where the schema fits (E020).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from langgraph_agent_builder.sdk import Component, Output, fields, ports
from langgraph_agent_builder.sdk.ports import PortFamily, PortSpec


class Ticket(BaseModel):
    id: str
    subject: str
    priority: str = "normal"


class TicketBatch(BaseModel):
    tickets: list[Ticket] = Field(default_factory=list)
    source: str = "manual"


TICKET_BATCH = PortSpec(
    schema_ref="ticket_triage:TicketBatch",
    json_schema=TicketBatch.model_json_schema(),
    family=PortFamily.DATA,
)


class TicketParser(Component):
    component_id = "ticket_triage.data.ticket_parser"
    display_name = "Ticket Parser"
    description = "Parses one-ticket-per-line text into a TicketBatch."
    icon = "ticket"
    category = "data"

    inputs = [fields.HandleField(name="text", display_name="Text", as_port=ports.TEXT)]
    outputs = [Output(name="batch", display_name="Ticket Batch", port=TICKET_BATCH)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            lines = str(ctx.get_input(state, "text") or "").splitlines()
            tickets = [
                Ticket(id=f"T{i}", subject=line.strip(),
                       priority="high" if "urgent" in line.lower() else "normal")
                for i, line in enumerate(lines, start=1)
                if line.strip()
            ]
            return {"batch": TicketBatch(tickets=tickets).model_dump()}

        return node


class TicketSummary(Component):
    component_id = "ticket_triage.data.ticket_summary"
    display_name = "Ticket Summary"
    description = "Summarizes a TicketBatch into text — accepts ONLY TicketBatch edges."
    icon = "clipboard-list"
    category = "data"

    inputs = [
        fields.HandleField(name="batch", display_name="Ticket Batch", as_port=TICKET_BATCH)
    ]
    outputs = [Output(name="text", display_name="Text", port=ports.TEXT)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            raw = ctx.get_input(state, "batch") or {}
            batch = TicketBatch.model_validate(raw)
            high = sum(1 for t in batch.tickets if t.priority == "high")
            return {"text": f"{len(batch.tickets)} tickets ({high} high priority)"}

        return node
