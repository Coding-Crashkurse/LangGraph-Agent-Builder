"""Unit tests for lga.components.data.helpers (MessageHistory, CurrentDate)."""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from lga.components.data.helpers import CurrentDate, MessageHistory
from lga.sdk.ports import Message
from lga.sdk.testing import ComponentTestHarness

# --------------------------------------------------------------------------- MessageHistory


async def test_message_history_converts_langchain_and_builds_table() -> None:
    node = ComponentTestHarness().build(MessageHistory, config={})
    state = {"messages": [HumanMessage(content="hi"), AIMessage(content="hello")]}
    out = await node(state)
    assert [m.role for m in out["messages"]] == ["user", "assistant"]
    assert out["table"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


async def test_message_history_filters_by_sender() -> None:
    node = ComponentTestHarness().build(MessageHistory, config={"sender": "assistant"})
    state = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content="a"),
            SystemMessage(content="sys"),
            AIMessage(content="b"),
        ]
    }
    out = await node(state)
    assert [m.content for m in out["messages"]] == ["a", "b"]


async def test_message_history_limits_to_last_n() -> None:
    node = ComponentTestHarness().build(MessageHistory, config={"n_messages": 2})
    msgs = [Message(role="user", content=str(i)) for i in range(5)]
    out = await node({"messages": msgs})
    assert [m.content for m in out["messages"]] == ["3", "4"]


async def test_message_history_empty_state_is_safe() -> None:
    node = ComponentTestHarness().build(MessageHistory, config={})
    out = await node({})
    assert out["messages"] == []
    assert out["table"] == []


async def test_message_history_keeps_existing_message_objects() -> None:
    existing = Message(role="tool", content="tool-out")
    node = ComponentTestHarness().build(MessageHistory, config={"sender": "tool"})
    out = await node({"messages": [existing, Message(role="user", content="q")]})
    assert out["messages"] == [existing]


# --------------------------------------------------------------------------- CurrentDate


async def test_current_date_year_in_utc() -> None:
    node = ComponentTestHarness().build(CurrentDate, config={"timezone": "UTC", "format": "%Y"})
    out = await node()
    assert out["text"] == str(datetime.now(UTC).year)


async def test_current_date_invalid_timezone_falls_back_to_utc() -> None:
    node = ComponentTestHarness().build(
        CurrentDate, config={"timezone": "Not/AZone", "format": "%Z"}
    )
    out = await node()
    assert out["text"] == "UTC"


async def test_current_date_uses_fixed_offset_timezone() -> None:
    # Asia/Tokyo has no DST, so the numeric UTC offset is stable at +0900.
    node = ComponentTestHarness().build(
        CurrentDate, config={"timezone": "Asia/Tokyo", "format": "%z"}
    )
    out = await node()
    assert out["text"] == "+0900"


async def test_current_date_defaults_when_config_empty() -> None:
    node = ComponentTestHarness().build(CurrentDate, config={"format": "%Y"})
    out = await node()
    assert out["text"] == str(datetime.now(UTC).year)
