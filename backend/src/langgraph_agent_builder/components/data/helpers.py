"""Data helper components (SPEC §12.6) — Message History, Current Date.

Langflow parity; no external memory backends in v1 — Message History reads the
checkpointed thread state directly.
"""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import BuildContext, NodeFn
from langgraph_agent_builder.sdk.ports import Message


class MessageHistory(Component):
    component_id = "lab.data.message_history"
    legacy = True
    display_name = "Message History"
    description = "Read the checkpointed thread's messages (Langflow parity)."
    icon = "history"
    category = "data"

    inputs = [
        fields.IntInput(name="n_messages", display_name="Messages", default=20, min=1, max=200),
        fields.DropdownInput(
            name="sender",
            display_name="Sender Filter",
            options=["all", "user", "assistant", "system", "tool"],
            default="all",
        ),
    ]
    outputs = [
        Output(name="messages", display_name="Messages", port=ports.MESSAGES),
        Output(name="table", display_name="Table", port=ports.TABLE),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            raw = state.get("messages") or []
            sender = str(ctx.get_field("sender") or "all")
            n = int(ctx.get_field("n_messages") or 20)
            messages: list[Message] = []
            for m in raw:
                msg = Message.from_langchain(m) if not isinstance(m, Message) else m
                if sender != "all" and msg.role != sender:
                    continue
                messages.append(msg)
            messages = messages[-n:]
            table = [{"role": m.role, "content": m.content} for m in messages]
            return {"messages": messages, "table": table}

        return node


_TIMEZONES = ["UTC", "US/Eastern", "US/Pacific", "Europe/Berlin", "Europe/London", "Asia/Tokyo"]


class CurrentDate(Component):
    component_id = "lab.data.current_date"
    legacy = True
    display_name = "Current Date"
    description = "Current date/time in a chosen timezone → Text (tool-ready)."
    icon = "calendar-clock"
    category = "data"
    tool_mode_supported = True
    tool_mode_default = True

    inputs = [
        fields.DropdownInput(
            name="timezone",
            display_name="Timezone",
            options=_TIMEZONES,
            default="UTC",
            combobox=True,  # suggestions only — any IANA zone can be typed (build tolerates it)
        ),
        fields.StrInput(
            name="format",
            display_name="Format",
            default="%Y-%m-%d %H:%M:%S %Z",
            advanced=True,
        ),
    ]
    outputs = [Output(name="text", display_name="Text", port=ports.TEXT)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            tz_name = str(ctx.get_field("timezone") or "UTC")
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = ZoneInfo("UTC")
            fmt = str(ctx.get_field("format") or "%Y-%m-%d %H:%M:%S %Z")
            return {"text": datetime.now(tz).strftime(fmt)}

        return node
